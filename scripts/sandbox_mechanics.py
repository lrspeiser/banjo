"""Reusable mechanical and optical sandbox pieces, built from general engine laws.

Fragments use the machine declaration schema. Names belong to the placement;
there are no level-name checks, scripted wins, or assigned launch velocities.
"""
import copy
import json
import math
from pathlib import Path

import machine_world as mw


def number(label, low, high, default, step=.01):
    return {'label': label, 'min': low, 'max': high, 'default': default, 'step': step}


def choice(label, choices, default):
    return {'label': label, 'choices': choices, 'default': default}


def box(name, size, at, material='concrete', fixed=True, **extra):
    return dict(name=name, shape='box', material=material, size_m=size, at_m=at, fixed=fixed, **extra)


def _position(k):
    return k.get('x_m', 0), k.get('z_m', 0)


def knife(name, k, ctx):
    import machine_game as mg
    # The blade must clear the ground for every allowed combination of knobs.
    # An invalid placement is refused; it is never silently moved to a target.
    return mg._knife(name, k, ctx)


def mirror(name, k, ctx):
    import machine_game as mg
    result = mg._mirror(name, k, ctx)
    result['parts'][0]['size_m'] = [.02, k.get('size_m', .2), k.get('size_m', .2)]
    return result


def lens(name, k, ctx):
    import machine_game as mg
    # Keep existing puzzle tray defaults while exposing independent controls.
    tray = dict(ctx.get('tray', {}))
    for key in ('height_m', 'radius_m', 'diameter_m'):
        if key in k:
            tray[key] = k[key]
    return mg._lens(name, k, {'tray': tray})


def solar(name, k, ctx):
    import machine_game as mg
    tray = dict(ctx.get('tray', {}))
    battery = k.get('battery', tray.get('battery', 'included battery'))
    included = battery == 'included battery'
    tray['battery'] = name + ' battery' if included else battery
    result = mg._solar(name, k, {'tray': tray})
    width = k.get('size_m', .5)
    result['parts'][0]['size_m'] = [width, .02, width]
    result['solar_panels'][0]['area_m2'] = width * width
    if included:
        x, z = _position(k)
        result['parts'].append(box(name + ' battery box', [.12, .12, .12], [x + .4, .06, z], 'iron'))
        result['batteries'] = [{'name': name + ' battery', 'in': name + ' battery box',
                                'capacity_j': 10000, 'charge_j': 0, 'voltage_v': 12}]
    if not ctx.get('spec', {}).get('sun'):
        # The declaration requires an environment even for an unlit panel.
        # A disabled sun makes a dry-table placement valid without free power.
        result['sun'] = {'elevation_deg': 50, 'azimuth_deg': 180, 'irradiance_w_m2': 0}
    return result


def tackle(name, k, ctx):
    import machine_game as mg
    if ctx.get('tray', {}).get('load'):
        return mg._tackle(name, k, ctx)
    x, z = _position(k)
    y = k.get('drop_from_m', 1.0)
    material, side = mg.COUNTERWEIGHTS[k.get('counterweight_kg', 2.7)]
    load_name = k.get('load', 'included load')
    included = load_name == 'included load'
    if included:
        load_name = name + ' load'
        load = box(load_name, [.14] * 3, [x + .6, .25, z], k.get('load_material', 'oak'), False)
    else:
        load = next((p for p in ctx['parts'] if p['name'] == load_name), None)
        if load is None or load['fixed']:
            raise ValueError('Choose an existing moving load for the block and tackle')
    beam = max(y + .4, load['at_m'][1] + .5 * load['size_m'][1] + .3)
    parts = [box(name, [side] * 3, [x, y, z], material, False),
             box(name + ' left post', [.08, beam, .08], [x - .2, beam / 2, z + .16]),
             box(name + ' right post', [.08, beam, .08], [load['at_m'][0] + .2, beam / 2, z + .16]),
             box(name + ' beam', [load['at_m'][0] - x + .48, .08, .32],
                 [(load['at_m'][0] + x) / 2, beam + .04, z])]
    if included:
        parts.append(load)
    joints = [{'name': name + ' rope', 'kind': 'pulley', 'a': name, 'b': load_name,
               'at_m': [x, y + side / 2, z],
               'at_b_m': [load['at_m'][0], load['at_m'][1] + load['size_m'][1] / 2, load['at_m'][2]],
               'over_a_m': [x, beam, z], 'over_b_m': [load['at_m'][0], beam, load['at_m'][2]],
               'ratio': k.get('ratio', 2)}]
    return {'parts': parts, 'joints': joints}


def weight(name, k, ctx):
    import machine_game as mg
    x, z = _position(k)
    side = k.get('size_m', .1)
    material = k.get('material', 'iron')
    mount = k.get('mount', 'loose')
    height = k.get('height_m', .6)
    if mount == 'hanging':
        return {'kits': [mg._turned_kit({'kit': 'hanging_weight', 'name': name,
                           'post_m': [x, 0, z + .235], 'drop_m': max(.01, height - side / 2),
                           'hang': 'rope', 'rope_m': .3, 'side': '-z',
                           'weight_material': material, 'weight_size_m': side}, k, [x, 0, z])]}
    part = box(name, [side] * 3, [x, max(side / 2 + .002, height), z], material, False,
               turn_deg=mw.turn_of(mw.heading(*(mg._turn(k) or [0, 0, 0]))))
    part['at_m'][1] = max(part['at_m'][1], mg._reach(part)[1] + .002)
    result = {'parts': [part]}
    if mount == 'guided':
        height = part['at_m'][1]
        support = box(name + ' guide', [.08, height + side, .08],
                      [x, (height + side) / 2, z + side / 2 + .06])
        result['parts'].append(support)
        result['joints'] = [{'name': name + ' slide', 'kind': 'slide', 'a': support['name'], 'b': name,
                             'at_m': list(part['at_m']), 'axis': [0, 1, 0], 'lower_m': -height,
                             'upper_m': 1, 'friction_n': 0}]
    return result


def spring(name, k, ctx):
    if k.get('mechanism_version', 1) == 3:
        return latched_spring(name, k, ctx)
    x, z = _position(k)
    height = k.get('height_m', .65)
    rest = k.get('rest_m', .5)
    # Linear force element, not a material model for the drawn coil.
    side = .12
    base = box(name + ' base', [.3, .08, .3], [x, .04, z])
    load = box(name + ' load', [side] * 3, [x, height, z], k.get('material', 'oak'), False)
    included=k.get('load','included load')=='included load'
    if not included:
        load=next((p for p in ctx['parts'] if p['name']==k['load']),None)
        if load is None or load['fixed']:raise ValueError('Choose an existing moving load for the spring')
        height=load['at_m'][1]
    guide = box(name + ' guide', [.06, height + .2, .06], [x, (height + .2) / 2, z + .18])
    return {'parts': [base, guide]+([load] if included else []), 'joints': [
        {'name': name + ' spring', 'kind': 'spring', 'a': base['name'], 'b': load['name'],
         'at_m': [x, .08, z], 'at_b_m': list(load['at_m']), 'rest_m': rest,
         'stiffness_n_m': k.get('stiffness_n_m', 200), 'damping_n_s_m': k.get('damping_n_s_m', 6)},
        {'name': name + ' slide', 'kind': 'slide', 'a': guide['name'], 'b': load['name'],
         'at_m': list(load['at_m']), 'axis': [0, 1, 0], 'lower_m': .145 - height,
         'upper_m': .4, 'friction_n': 0}]}


def latched_spring(name, k, ctx):
    """Ideal axial spring and releasable restraint; the plate contacts the load.

    The coil in the viewer depicts this force element, not resolved wire stress.
    No joint connects the spring assembly to a separately placed load.
    """
    import machine_game as mg
    x, z = _position(k)
    held = k.get('compressed_m', .2)
    base = box(name+' base', [.3,.08,.3], [x,.04,z])
    plate = box(name+' push plate', [.065,.04,.14], [x,.10+held,z], 'iron', False)
    guide = box(name+' guide', [.025,.7,.025], [x,.35,z+.18], 'iron')
    parts = [base, guide, plate]
    joints = [
        dict(name=name+' spring',kind='spring',a=base['name'],b=plate['name'],
             at_m=[x,.08,z],at_b_m=[x,.08+held,z],rest_m=k.get('rest_m',.5),
             stiffness_n_m=k.get('stiffness_n_m',200),damping_n_s_m=k.get('damping_n_s_m',6)),
        dict(name=name+' slide',kind='slide',a=guide['name'],b=plate['name'],
             at_m=list(plate['at_m']),axis=[0,1,0],lower_m=.002-held,upper_m=.4,friction_n=0),
        dict(name=name+' restraint',kind='fix',a=guide['name'],b=plate['name'],at_m=list(plate['at_m']))]
    mw.turn_rows(mw.heading(*(mg._turn(k) or [0,0,0])),[x,.04,z],parts,joints)
    # Lift a tilted base clear of the floor; generated stands carry its weight.
    lift=max(0, max(mg._reach(p)[1]-p['at_m'][1] for p in parts if p['fixed']))
    if lift: mw.shift_rows([0,lift,0],parts+joints)
    if k.get('load','included load')=='included load':
        parts.append(box(name+' load',[.12]*3,[x,plate['at_m'][1]+.08,z],k.get('material','oak'),False))
    elif not any(p['name']==k['load'] and not p['fixed'] for p in ctx['parts']):
        raise ValueError('Choose an existing moving load for the spring')
    return dict(parts=parts,joints=joints)


def gear(name, k, ctx):
    """One mounted wheel. Boxes form its teeth; native contacts carry torque.

    No ratio joint, motor, battery or partner is created by this builder.
    The simple rectangular profile is deliberately not an involute gear.
    """
    x, z = _position(k)
    teeth = int(k.get('teeth', 12))
    module = k.get('module_m', .024)
    radius = teeth * module / 2
    height = k.get('height_m', .65)
    phase = math.radians(k.get('phase_deg', 0))
    root = radius - .7 * module
    tooth_depth = 1.4 * module
    tooth_width = 1.1 * module
    shapes = [{'shape': 'cylinder', 'size_m': [2 * root, .04, 2 * root],
               'at_m': [0, 0, 0], 'turn_deg': [90, 0, 0]}]
    for i in range(teeth):
        angle = phase + 2 * math.pi * i / teeth
        shapes.append({'shape':'box','size_m':[tooth_depth,tooth_width,.04],
                       'at_m':[radius * math.cos(angle),radius * math.sin(angle),0],
                       'turn_deg':[0,0,math.degrees(angle)]})
    shapes.append({'shape':'box','size_m':[.014,radius,.008],
                   'at_m':[0,radius / 2,.024]})
    return {'parts': [box(name+' post',[.06,height,.06],[x,height / 2,z-.1]),
        {'name':name+' wheel','shape':'compound','material':k.get('material','aluminum'),
         'at_m':[x,height,z],'parts':shapes}],
        'joints':[{'name':name+' axle','kind':'hinge','a':name+' post','b':name+' wheel',
                   'at_m':[x,height,z],'axis':[0,0,1],
                   'friction_n_m':k.get('friction_n_m',.001)}]}


def gears(name, k, ctx):
    x, z = _position(k)
    height = k.get('height_m', .4)
    a_teeth, b_teeth = int(k.get('teeth_a', 12)), int(k.get('teeth_b', 24))
    radius_a, radius_b = a_teeth * .008, b_teeth * .008
    out_x = x + radius_a + radius_b + .02
    parts, joints = [], []
    for which, pos, radius in (('input', x, radius_a), ('output', out_x, radius_b)):
        body = name + ' ' + which + ' wheel'
        post = name + ' ' + which + ' post'
        parts += [box(post, [.08, height, .08], [pos, height / 2, z - .12]),
                  {'name': body, 'shape': 'compound', 'material': 'aluminum', 'at_m': [pos, height, z],
                   'parts': [{'shape': 'cylinder', 'size_m': [2 * radius, .04, 2 * radius],
                              'at_m': [0, 0, 0], 'turn_deg': [90, 0, 0]},
                             {'shape': 'box', 'size_m': [.02, radius, .02], 'at_m': [0, radius / 2, .03]}]}]
        joints.append({'name': name + ' ' + which + ' axle', 'kind': 'hinge', 'a': post, 'b': body,
                       'at_m': [pos, height, z], 'axis': [0, 0, 1],
                       'lower_deg': -180, 'upper_deg': 180, 'friction_n_m': k.get('friction_n_m', .02)})
    joints.append({'name': name + ' coupling', 'kind': 'gear', 'a': name + ' input axle',
                   'b': name + ' output axle', 'teeth_a': a_teeth, 'teeth_b': b_teeth})
    result = {'parts': parts, 'joints': joints}
    drive = k.get('drive', 'off')
    if drive != 'off':
        result['parts'].append(box(name + ' battery box', [.12] * 3, [x - .3, .06, z - .3], 'iron'))
        result['batteries'] = [{'name': name + ' battery', 'in': name + ' battery box',
                                'capacity_j': 50000, 'voltage_v': 24}]
        result['circuits'] = [{'name': name + ' drive', 'battery': name + ' battery',
                               'motor': {'hinge': name + ' input axle', 'stall_torque_n_m': 2,
                                         'no_load_rad_s': 6, 'command': 1 if drive == 'forward' else -1}}]
    return result


# A ring marble: an iron marble with an iron tie ring fixed on top, so a
# string has somewhere to tie. The ring is its own body (eight short bars
# round a 20 mm circle, its hole along z), welded to the ball 1 mm above it
# with a fixed joint, as glue joins two pieces. Nothing about rolling is
# scripted. The ring is wider than the ball (44 mm across against 40 mm), so
# whichever way the marble rolls the ring reaches the floor: a narrower ring
# let it roll like a wheel about the ring's axis, curving but rolling on.
RING_MARBLE_D = .04
RING_R = .02        # the ring's centre-line radius
RING_WIRE = .004    # the ring's bar thickness
RING_GAP = .001     # between the ball's top and the ring
RING_TIE = dict(part=' ring', at_m=[0, RING_R, 0])  # where a string ties: the ring's top bar


def ring_marble(name, k, ctx):
    import machine_game as mg
    d, (x, z) = RING_MARBLE_D, _position(k)
    ball = {'name': name, 'shape': 'sphere', 'material': 'iron', 'size_m': [d, d, d],
            'at_m': [x, 0.0, z], 'turn_deg': [0.0, 0.0, 0.0], 'fixed': False}
    ball['at_m'][1] = round(mg.rest_height(ball, ctx['parts']), 4)
    top = ball['at_m'][1] + d / 2
    chord = 2 * (RING_R + RING_WIRE / 2) * math.tan(math.pi / 8)
    bars = [{'shape': 'box', 'size_m': [round(chord, 5), RING_WIRE, RING_WIRE],
             'at_m': [round(RING_R * math.sin(a), 5), round(-RING_R * math.cos(a), 5), 0],
             'turn_deg': [0, 0, round(math.degrees(a), 3)]}
            for a in (2 * math.pi * i / 8 for i in range(8))]
    ring = {'name': name + ' ring', 'shape': 'compound', 'material': 'iron', 'fixed': False,
            'at_m': [x, round(top + RING_GAP + RING_WIRE / 2 + RING_R, 4), z], 'parts': bars}
    weld = {'name': name + ' weld', 'kind': 'fix', 'a': name, 'b': name + ' ring',
            'at_m': [x, round(top + RING_GAP / 2, 4), z], 'axis': [0.0, 1.0, 0.0]}
    return {'parts': [ball, ring], 'joints': [weld]}


PIECES = {'knife': knife, 'mirror': mirror, 'lens': lens, 'solar': solar,
          'tackle': tackle, 'weight': weight, 'spring': spring, 'gears': gears, 'gear':gear,
          'ring_marble': ring_marble}


def tray(piece, title, knobs, **extra):
    return dict(piece=piece, title=title, count=99, cost=0, knobs=dict(
        x_m=number('Position along (m)', -2, 2, 0), z_m=number('Position across (m)', -2, 2, 0), **knobs), **extra)


TRAY = [
    tray('knife', 'Knife pendulum', {'pivot_height_m': number('Pivot height (m)', .9, 2, 1.31),
         'arm_m': number('Arm length (m)', .3, .8, .6),
         'swing_toward': choice('Swing direction', ['+x', '-x', '+z', '-z'], '+x'),
         'edge_radius_m': number('Edge radius (m)', .0001, .002, .0002, .0001)}),
    tray('mirror', 'Mirror', {'angle_deg': dict(number('Mirror angle', -180, 180, 45, 1), turning=True),
         'height_m': number('Beam height (m)', .2, 1.5, .575),
         'size_m': number('Mirror size (m)', .1, .4, .2, .02)}),
    tray('lens', 'Lens', {'height_m': number('Beam height (m)', .2, 1.5, .575),
         'shape': choice('Lens shape', ['convex', 'concave'], 'convex'),
         'radius_m': number('Face radius (m)', .1, .5, .2),
         'diameter_m': number('Diameter (m)', .04, .12, .1, .02)}),
    tray('solar', 'Solar panel', {'height_m': number('Post height (m)', .3, 1, .5),
         'size_m': number('Panel width (m)', .2, .6, .5, .02),
         'battery': {'part': True, 'default': 'included battery', 'label': 'Battery store'} }),
    tray('tackle', 'Block and tackle', {'drop_from_m': number('Counterweight height (m)', .6, 1.3, 1),
         'ratio': choice('Rope ratio', [1, 2, 3, 4], 2),
         'counterweight_kg': choice('Counterweight preset (kg)', [2.7, 4.0, 4.7, 7.4, 7.9, 13.6, 21.6], 2.7),
         'load_material': choice('Included load material', ['oak', 'glass', 'iron'], 'oak'),
         'load': {'part': True, 'default': 'included load', 'label': 'Load'}}, turning=False),
    tray('weight', 'Weight', {'size_m': number('Weight side (m)', .06, .2, .1, .02),
         'height_m': number('Starting height (m)', .15, 1.5, .6),
         'material': choice('Material', ['oak', 'glass', 'iron'], 'iron'),
         'mount': choice('Mounting', ['loose', 'hanging', 'guided'], 'loose')}),
    tray('spring', 'Latched spring', {'height_m': dict(number('Starting height (m)', .4, .9, .65),hidden=True),
         'mechanism_version':dict(choice('Spring construction',[1,3],3),legacy_default=1,hidden=True),
         'compressed_m':number('Held spring length (m)',.1,.4,.2),
         'rest_m': number('Relaxed length (m)', .2, .7, .5),
         'stiffness_n_m': number('Stiffness (N/m)', 50, 1000, 200, 10),
         'damping_n_s_m': number('Internal damping (N s/m)', 0, 30, 6, 1),
         'material': choice('Load material', ['oak', 'glass', 'iron'], 'oak'),
         'load': {'part':True,'default':'included load','label':'Load'}}),
    tray('gear','Gear',{'height_m':number('Axle height (m)',.35,.9,.65),
         'teeth':choice('Teeth',[12,18,24,36],12),
         'module_m':choice('Tooth size (m)',[.016,.024,.032],.024),
         'phase_deg':number('Tooth alignment (degrees)',0,360,0,1),
         'material':choice('Material',['aluminum','oak','glass','iron'],'aluminum'),
         'friction_n_m':number('Bearing friction (N m)',0,.1,.001,.001)},turning=False,
         primary_knobs=['teeth','module_m','height_m']),
    tray('ring_marble', 'Ring marble', {}, turning=False, tie_on=RING_TIE),
    tray('gears', 'Gear pair (saved designs)', {'height_m': number('Axle height (m)', .35, .8, .4),
         'teeth_a': choice('Input teeth', [12, 18, 24], 12),
         'teeth_b': choice('Output teeth', [12, 18, 24], 24),
         'friction_n_m': number('Bearing friction (N m)', 0, .1, .02, .01),
         'drive': choice('Included battery drive', ['off', 'forward', 'reverse'], 'off')}, turning=False, legacy=True),
]


def base(title, **fields):
    # Empty machines are valid: only parts with a physical role belong here.
    return dict(schema=mw.SCHEMA, title=title, cell_m=.02,
                parts=[], stations=[], **fields)


def optical_base(title, target, normal, watts=10, beam_width=.02):
    spec = base(title)
    dimensions = [.12, .12, .12]
    dimensions[next(i for i, v in enumerate(normal) if abs(v) > .5)] = .02
    behind = [target[i] - normal[i] * .01 for i in range(3)]
    spec['parts'] = [box('source battery box', [.12] * 3, [-1, .06, .3], 'iron'),
                     box('sensor plate', dimensions, behind),
                     box('sensor post', [.04, .515, .04], [behind[0], .2575, behind[2]]),
                     box('source post', [.04, .56, .04], [-.835, .28, 0])]
    spec['batteries'] = [{'name': 'source battery', 'in': 'source battery box', 'capacity_j': 10000, 'voltage_v': 12}]
    spec['kits'] = [{'kit': 'laser', 'name': 'source', 'at_m': [-.8, .575, 0], 'aim': [1, 0, 0],
                     'battery': 'source battery', 'watts': watts, 'efficiency': .9, 'beam_width_m': beam_width}]
    spec['light'] = {'photocells': [{'name': 'target', 'on': 'sensor plate', 'at_m': list(target),
                                    'normal': normal, 'area_m2': .0004}]}
    spec['stations'] = [{'title': 'Light reaches the sensor', 'done_when': {'lit_w': {'photocell': 'target', 'w': .2}},
                          'focus': ['sensor plate']}]
    return spec


def _templates():
    levels = json.loads((Path(__file__).resolve().parents[1] / 'client/voxel-lab/levels.json').read_text(encoding='utf-8'))
    cut = next(l for l in levels['levels'] if l['id'] == 'cut')
    sun = base('Charge in the sun', sun={'elevation_deg': 20, 'azimuth_deg': 180, 'irradiance_w_m2': 1000})
    gear = base('Fast wheel slow wheel')
    # Stations referring to a placement are added after assembly, rather than
    # putting unresolved references into an independently valid saved base.
    bounce = base('Bounce and settle')
    lift = base('Lift with less')
    tip = base('Tip the lever', kits=[{'kit': 'lever', 'name': 'lever', 'pivot_m': [0, .2, 0],
                                      'length_m': .7, 'width_m': .14, 'thickness_m': .02, 'limit_deg': 25, 'along': 'x'}])
    tip['stations'] = [{'title': 'The lever tips', 'done_when': {'turned_deg': {'joint': 'lever hinge', 'deg': 15}}}]
    return [
        {'name': 'Cut and catch', 'description': 'Gravity swings an edge through an oak cord; move it aside to miss.',
         'base': copy.deepcopy(cut['machine']), 'placements': copy.deepcopy(cut['solution'])},
        {'name': 'Around the corner', 'description': 'Aim a low-power beam at a sensor using a polished mirror.',
         'base': optical_base('Around the corner', [.5, .575, 1], [0, 0, -1]),
         'placements': [{'piece': 'mirror', 'x_m': .5 + .01 * math.sqrt(2), 'angle_deg': 45}]},
        {'name': 'Find the focus', 'description': 'Slide or change a curved glass lens and compare received light.',
         'base': optical_base('Find the focus', [.29, .575, 0], [-1, 0, 0], beam_width=.12),
         'placements': [{'piece': 'lens', 'x_m': .1, 'radius_m': .2, 'diameter_m': .12}]},
        {'name': 'Charge in the sun', 'description': 'Tilt the panel toward the fixed low sun; read watts and stored charge.',
         'base': sun, 'placements': [{'piece': 'solar', 'yaw_deg': -90, 'pitch_deg': 70}]},
        {'name': 'Lift with less', 'description': 'Change rope ratio or the material-derived counterweight preset.',
         'base': lift, 'placements': [{'piece': 'tackle'}]},
        {'name': 'Bounce and settle', 'description': 'A guided load compresses a linear spring; compare damping and stiffness.',
         'base': bounce, 'placements': [{'piece': 'spring','mechanism_version':1}]},
        {'name': 'Fast wheel slow wheel', 'description': 'A finite battery motor drives a 12:24 ideal gear coupling.',
         'base': gear, 'placements': [{'piece': 'gears', 'drive': 'forward'}]},
        {'name': 'Tip the lever', 'description': 'A loose weight falls onto the end of a supported lever.',
         'base': tip, 'placements': [{'piece': 'weight', 'x_m': -.25, 'height_m': .45, 'size_m': .1}]},
    ]


def templates():
    return copy.deepcopy(TEMPLATES)


TEMPLATES = _templates()
for _example in TEMPLATES:
    _example['pieces'] = [p['piece'] for p in _example['placements']]


def _easy_levels():
    """A single physical decision per challenge; answers stay server-side."""
    settings = [
        ('easy-cut', 'Cut the cord', 'knife', 'Move the pendulum edge into the oak cord.',
         {'in_zone': {'part': 'weight', 'at_m': [0, .08, .235], 'size_m': [.36, .16, .34]}},
         {}, {'x_m': -.6}, 2),
        ('easy-mirror', 'Bounce to the target', 'mirror', 'Turn the mirror until its reflected beam reaches the sensor.',
         {'lit_w': {'photocell': 'target', 'w': .2}}, {}, {'angle_deg': 0}, 1),
        ('easy-lens', 'Find the focus', 'lens', 'Place the convex lens in the broad beam.',
         {'lit_w': {'photocell': 'target', 'w': 2}}, {}, {'z_m': .3}, 1),
        ('easy-solar', 'Catch the sun', 'solar', 'Tip the connected panel toward the fixed low sun.',
         {'charged_j': {'battery': 'your solar 1 battery', 'at_least_j': 20}}, {}, {'pitch_deg': 0}, 1),
        ('easy-tackle', 'Raise the crate', 'tackle', 'Choose enough counterweight to raise the glass load.',
         {'rose_m': {'part': 'your tackle 1 load', 'm': .25}},
         {'load_material': 'glass', 'counterweight_kg': 4.7}, {'counterweight_kg': 2.7}, 2),
        ('easy-spring', 'Spring lifts the load', 'spring', 'Lengthen the relaxed spring to store energy before the run.',
         {'rose_m': {'part': 'your spring 1 load', 'm': .05}},
         {'height_m': .4, 'rest_m': .7}, {'rest_m': .2}, 1),
        ('easy-gears', 'Turn the big wheel', 'gears', 'Choose forward drive on the prebuilt motor and gear pair. The included finite battery powers its axle; the teeth transfer torque to the big wheel.',
         {'turned_deg': {'joint': 'your gears 1 output axle', 'deg': 180}}, {}, {'drive': 'off'}, 2),
        ('easy-weight', 'Tip the lever', 'weight', 'Put the raised weight above one end of the lever.',
         {'turned_deg': {'joint': 'lever hinge', 'deg': 15}}, {}, {'x_m': 0}, 1.5),
    ]
    # Rounded upward to three significant figures from the native rehearsal
    # of each own solution (material-derived embodied cost plus run energy).
    energy_pars = {'knife': 380000000, 'mirror': 337000000, 'lens': 23500000,
                   'solar': 532000000, 'tackle': 930000000, 'spring': 34000000,
                   'gears': 2830000000, 'weight': 197000000}
    out = []
    for identity, title, piece, brief, rule, settings_, wrong, seconds in settings:
        example = next(t for t in TEMPLATES if t['pieces'] == [piece])
        row = copy.deepcopy(next(t for t in TRAY if t['piece'] == piece))
        row.update(count=1, sandbox_builder=True)
        solution = copy.deepcopy(example['placements'])
        solution[0].update(settings_)
        bad = copy.deepcopy(solution)
        bad[0].update(wrong)
        out.append({'id': identity, 'title': title, 'difficulty': 'easy', 'teaches': piece,
                    'brief': brief, 'time_s': seconds, 'budget': 100, 'par': 100, 'style_pieces': 1,
                    'par_energy_j': energy_pars[piece],
                    'machine': copy.deepcopy(example['base']), 'custom_base': True, 'tray': [row],
                    'hints': [brief, 'Copy the matching sandbox example to compare a working setup.'],
                    'goal': {'title': title, 'station': {'done_when': rule}},
                    'solution': solution, 'wrong': bad})
    return out


EASY_LEVELS = _easy_levels()
LEGACY_LEVELS={row['id']:copy.deepcopy(row) for row in EASY_LEVELS}

# Goal objects belong to the starting apparatus, not to the added device.
_spring_lesson=next(row for row in EASY_LEVELS if row['id']=='easy-spring')
_spring_lesson['machine']['parts']=[
    box('spring load',[.12]*3,[0,.4,0],'oak',False),
    box('load cradle post',[.2,.34,.06],[0,.17,.35]),
    box('load cradle left fork',[.02,.02,.42],[-.05,.33,.14]),
    box('load cradle right fork',[.02,.02,.42],[.05,.33,.14])]
_spring_lesson['goal']['station']['done_when']={'rose_m':{'part':'spring load','m':.05}}
_spring_lesson['goal']['focus']=['spring load']
_spring_lesson['goal']['area']=dict(at_m=[0,.51,0],size_m=[.22,.02,.22])
_spring_lesson['par_energy_j']=21341800
_spring_lesson['tray'][0]['knobs']['load'].update(default='spring load',choices=['spring load'])
_spring_lesson['tray'][0]['knobs']['height_m'].update(default=.4,min=.4,max=.4)
_spring_lesson['tray'][0]['knobs']['rest_m']['default']=.2
_spring_lesson['tray'][0].update(start_at_defaults=True,focus_knob='rest_m')
for key in ('solution','wrong'):_spring_lesson[key][0]['load']='spring load'
_spring_lesson['brief']='Place the spring beneath the waiting oak load. Increase its relaxed length to lift the load five centimetres off its cradle.'
_spring_lesson['hints'][0]=_spring_lesson['brief']

# Keep old shared challenges and saved spring constructions reproducible.
LEGACY_SPRING_STARTER=copy.deepcopy(_spring_lesson)
LEGACY_SPRING_STARTER['tray'][0]['turning']=False
LEGACY_SPRING_STARTER['tray'][0]['knobs']['mechanism_version']['default']=1
for _old in list(LEGACY_LEVELS.values())+[LEGACY_SPRING_STARTER]:
    for _row in _old['tray']:
        if _row['piece']=='spring':
            _row['turning']=False
            _row['knobs']['mechanism_version']['default']=1
_spring_lesson['tray'][0]['turning']=True
for _support in _spring_lesson['machine']['parts']:
    if _support['name'].startswith('load cradle'):
        _support['at_m'][2]*=-1
_spring_lesson['tray'][0]['knobs']['mechanism_version']['legacy_default']=3
_spring_lesson['tray'][0]['knobs']['compressed_m'].update(min=.2,max=.2,default=.2,hidden=True)
for key in ('solution','wrong'):
    _spring_lesson[key][0]['mechanism_version']=3
_spring_lesson['solution_releases']=['your spring 1 restraint']
_spring_lesson['release_to_start']=True
_spring_lesson['camera_min_m']=1.1
_spring_lesson['par_energy_j']=137614000
_spring_lesson['brief']='Place the spring under the oak box, increase its relaxed length to compress it, then release its latch to push the box above the green mark.'
_spring_lesson['hints']=[_spring_lesson['brief'],'The narrow push plate must fit between the two cradle forks. Run readies the spring; Release spring beside it starts the run.']
_latched_example=copy.deepcopy(_spring_lesson['machine'])
_latched_example['stations']=[dict(title='The box rises',done_when=copy.deepcopy(_spring_lesson['goal']['station']['done_when']))]
TEMPLATES.append(dict(name='Latch and lift',description='Aim a compressed spring under a waiting box, then release its latch. The push plate lifts the box through contact.',
    base=_latched_example,placements=copy.deepcopy(_spring_lesson['solution']),pieces=['spring']))

_tackle_lesson=next(row for row in EASY_LEVELS if row['id']=='easy-tackle')
_tackle_lesson['machine']['parts']=[box('crate',[.14]*3,[.6,.25,0],'glass',False),
    box('crate pedestal',[.22,.18,.22],[.6,.09,0])]
_tackle_lesson['goal']['station']['done_when']={'rose_m':{'part':'crate','m':.25}}
_tackle_lesson['goal']['focus']=['crate']
_tackle_lesson['goal']['area']=dict(at_m=[.6,.57,0],size_m=[.24,.02,.24])
_tackle_lesson['par_energy_j']=827064040
_tackle_lesson['tray'][0]['knobs']['load'].update(default='crate',choices=['crate'])
_tackle_lesson['tray'][0].update(start_at_defaults=True,focus_knob='counterweight_kg')
for key in ('solution','wrong'):_tackle_lesson[key][0]['load']='crate'
_tackle_lesson['brief']='The glass crate is waiting on its pedestal. Add the tackle and choose enough counterweight to lift it twenty-five centimetres.'
_tackle_lesson['hints'][0]=_tackle_lesson['brief']

import sandbox_electrics as _starter_electrics
_gear_lesson=next(row for row in EASY_LEVELS if row['id']=='easy-gears')
_gear_lesson['machine'].update(gears('target gears',dict(drive='off'),{}))
_starter_electrics.merge(_gear_lesson['machine'],_starter_electrics.battery('supply',dict(x_m=-.6),{}))
_gear_motor=_starter_electrics.tray('motor',connect_to={'plus':'supply:plus','minus':'supply:minus'})
_gear_motor.update(count=1,sandbox_builder=True,start_at_defaults=True,focus_knob='throttle')
_gear_motor['knobs']['hinge'].update(default='target gears input axle',choices=['target gears input axle'])
_gear_motor['knobs']['z_m']['default']=-.2
_gear_motor['knobs']['throttle']['default']=0
_gear_lesson['tray']=[_gear_motor]
_gear_lesson['goal']['station']['done_when']={'turned_deg':{'joint':'target gears output axle','deg':180}}
_gear_lesson['goal']['focus']=['target gears output wheel']
_gear_lesson['par_energy_j']=32833000
_gear_lesson['solution']=[dict(piece='motor',hinge='target gears input axle',x_m=0,z_m=-.2,throttle=1)]
_gear_lesson['wrong']=[dict(_gear_lesson['solution'][0],throttle=0)]
_gear_lesson['brief']='The gear pair is already here. Add the motor, increase its throttle and turn the big wheel through half a revolution.'
_gear_lesson['hints'][0]=_gear_lesson['brief']

# Preserve the published v2 apparatus and the old paired sandbox example.
LEGACY_GEARED_STARTER=copy.deepcopy(_gear_lesson)
LEGACY_GEAR_TEMPLATE=copy.deepcopy(next(row for row in TEMPLATES if row['name']=='Fast wheel slow wheel'))


def gear_workbench():
    apparatus=base('Bridge the gear gap')
    for name,knobs in [('drive gear',dict(x_m=-.31)),
                       ('target gear',dict(x_m=.45,teeth=24))]:
        _starter_electrics.merge(apparatus,gear(name,knobs,{}))
    _starter_electrics.merge(apparatus,_starter_electrics.battery('supply',dict(x_m=-.8,z_m=-.4),{}))
    _starter_electrics.merge(apparatus,_starter_electrics.motor('drive motor',
        dict(x_m=-.31,z_m=-.3,hinge='drive gear axle'),{}))
    housing=next(p for p in apparatus['parts'] if p['name']=='drive motor housing')
    housing.update(at_m=[-.31,.65,-.1],size_m=[.14,.14,.1])
    apparatus['electrical']['devices'][-1]['terminals']=_starter_electrics.motor_terminals(housing)
    # A declared 4 N m actuator is sized for the three aluminum wheels.
    # Its native finite-power torque/speed law still determines every angle.
    apparatus['electrical']['devices'][-1]['stall_torque_n_m']=4
    _starter_electrics.link(apparatus,'motor supply','supply:plus','drive motor:plus')
    _starter_electrics.link(apparatus,'motor return','drive motor:minus','supply:minus')
    return apparatus


_gear_lesson['machine']=gear_workbench()
_gear_row=copy.deepcopy(next(row for row in TRAY if row['piece']=='gear'))
_gear_row.update(count=1,sandbox_builder=True,start_at_defaults=True,focus_knob='teeth',frame_on_add=True)
_gear_row['knobs']['x_m']['default']=-1
_gear_row['knobs']['z_m']['default']=.4
_gear_row['knobs']['teeth'].update(default=18)
_gear_row['knobs']['phase_deg']['default']=15
_gear_lesson['tray']=[_gear_row]
_gear_lesson['goal']['station']['done_when']={'turned_deg':{'joint':'target gear axle','deg':180}}
_gear_lesson['goal']['focus']=['target gear wheel']
_gear_lesson['par_energy_j']=1050000000  # 1,041,093,292 J fabrication + 27.117 J native source use.
_gear_lesson['solution']=[dict(piece='gear',teeth=12,phase_deg=15,x_m=0,z_m=0)]
_gear_lesson['wrong']=[dict(_gear_lesson['solution'][0],z_m=.2)]
_gear_lesson['brief']='Bridge the gap between the powered gear and the big wheel. Choose a gear size and place its teeth between theirs to turn the big wheel halfway.'
_gear_lesson['hints']=[_gear_lesson['brief'],
    'The battery and its two wires power the motor on the left. Your gear has no built-in drive.',
    'Try twelve teeth with the axle at the same height. Teeth must reach both neighbours without overlapping; use tooth alignment for a small adjustment.']
_gear_example=next(row for row in TEMPLATES if row['name']=='Fast wheel slow wheel')
_gear_example.update(base=gear_workbench(),placements=copy.deepcopy(_gear_lesson['solution']),
    description='Three independent toothed wheels: a wired finite battery motor drives the small gear; contact with the middle gear turns the big one.')

# The current collector lesson includes the same two player decisions as the
# winch: get into sunlight and explicitly deliver that energy to a receiver.
# _easy_levels() retains the v1 apparatus for old seeded share links.
_solar_lesson = next(level for level in EASY_LEVELS if level['id']=='easy-solar')
_solar_lesson['machine']['parts'] = [
    box('shade wall',[2,1.6,.12],[0,.8,-.9]),
    box('solar battery box',[.12,.12,.12],[1.6,.06,.6],'iron')]
_solar_lesson['machine']['batteries'] = [{'name':'solar battery','in':'solar battery box',
    'capacity_j':10000,'charge_j':0,'voltage_v':12}]
_solar_lesson['machine']['electrical'] = dict(power_ports=[dict(name='battery:power',kind='input',
    battery='solar battery',part='solar battery box',at_m=[1.6,.14,.6])])
_solar_lesson['tray'][0].update(explicit_power=True,battery='solar battery')
_solar_lesson['tray'][0]['knobs'].pop('battery')
import sandbox_electrics as _electrics
_solar_lesson['tray'].append(_electrics.tray('power_cable'))
_solar_lesson['solution'][0].update(x_m=1.4,z_m=0)
_solar_lesson['solution'].append(dict(piece='power_cable',a_port='your solar 1:power',b_port='battery:power'))
_solar_lesson['wrong'] = copy.deepcopy(_solar_lesson['solution'])
_solar_lesson['wrong'][0]['pitch_deg'] = 0
_solar_lesson['goal']['station']['done_when']['charged_j']['battery'] = 'solar battery'
_solar_lesson['brief'] = 'Move the panel out of the wall’s shadow and aim it at the low sun. Click Connect wires in Controls, then connect its output to the battery input to deliver 20 J.'
_solar_lesson['hints'] = [_solar_lesson['brief'],
    'The wall blocks sunlight behind it. A panel at either side can collect power; the watts meter and the ray to the sun show whether it is shaded.',
    'Choose Connect wires in Controls, then click panel Out and battery In. Without the cable only the panel’s local store charges.']
_solar_lesson['par_energy_j'] = 192000000  # 191,439,840 J fabrication, rounded up to three figures


# ---- starter lessons: a ball, a block and a rope ------------------------------
# Three first lessons teach the primitives before the block and tackle. A
# win comes only from native gravity, contact and (for the rope) a
# tension-only tie joint. Nothing scripts a motion or checks a piece's name.
# They use the core marble, block and link builders, so the base gets the
# usual level stands (no custom_base) and old saves are unaffected.

def _starter_row(piece, knobs, **extra):
    return dict(piece=piece, count=1, cost=0, knobs=knobs, start_at_defaults=True, **extra)


def _starter_level(identity, title, teaches, brief, machine, tray, goal, solution, wrong, seconds, hint, par):
    return {'id': identity, 'title': title, 'difficulty': 'easy', 'teaches': teaches, 'brief': brief,
            'time_s': seconds, 'budget': 100, 'par': 100, 'style_pieces': 1, 'par_energy_j': par,
            'machine': machine, 'tray': tray, 'goal': goal, 'hints': [brief, hint],
            'solution': solution, 'wrong': wrong}


def _starter_levels():
    # Roll the ball: an oak slope, a cup on the floor beyond its foot.
    roll = base('Roll the ball')
    roll['kits'] = [dict(kit='ramp', name='slope', top_m=[-.9, .4, 0], bottom_m=[-.3, .06, 0],
                         width_m=.12, material='oak')]
    roll['parts'] = [box('cup back', [.04, .1, .3], [.88, .05, 0]),
                     box('cup left', [.36, .06, .04], [.68, .03, .13]),
                     box('cup right', [.36, .06, .04], [.68, .03, -.13])]
    marble = _starter_row('marble', dict(x_m=number('Position along (m)', -1, .2, .1),
                                         z_m=number('Position across (m)', -.4, .4, 0)), turning=False)
    roll_level = _starter_level('easy-roll', 'Roll the ball', 'gravity and rolling',
        'Set the marble down on the slope. Gravity rolls it down and along the floor into the green cup.',
        roll, [marble],
        {'title': 'The marble is in the cup', 'focus': ['your marble 1'], 'needs': 'Place the marble first.',
         'station': {'done_when': {'in_zone': {'part': 'your marble 1', 'at_m': [.68, .03, 0], 'size_m': [.36, .1, .22]}}}},
        [dict(piece='marble', x_m=-.7, z_m=0)], [dict(piece='marble', x_m=0, z_m=0)], 3,
        'A marble on flat ground stays where it is. Only a slope gives gravity a direction to roll it.',
        6600000)  # 6,593,156 J: the 0.264 kg iron marble's fabrication energy, rounded up

    # Fill the trench: the gap level's ramp and tables, with a 30 cm trench
    # whose floor is the ground. A fixed block is set down on what is under it.
    trench = base('Fill the trench')
    trench['kits'] = [dict(kit='ramp', name='start ramp', top_m=[-1.3, .62, 0], bottom_m=[-.7, .3, 0],
                           width_m=.12, ball=dict(material='iron', diameter_m=.06, name='ball'))]
    trench['parts'] = [box('near table', [.6, .3, .3], [-.4, .15, 0]),
                       box('far table', [.9, .3, .3], [.65, .15, 0]),
                       box('cup back', [.04, .1, .3], [1.08, .35, 0]),
                       box('cup left', [.34, .06, .04], [.89, .33, .13]),
                       box('cup right', [.34, .06, .04], [.89, .33, -.13])]
    block = _starter_row('block', dict(
        x_m=number('Position along (m)', -.6, 1, .5), z_m=number('Position across (m)', -.4, .4, 0),
        length_m=dict(number('Length (m)', .26, .26, .26), hidden=True),
        tall_m=number('Height (m)', .04, .5, .1, .02),
        depth_m=dict(number('Depth (m)', .3, .3, .3), hidden=True),
        material=dict(choice('Material', ['concrete'], 'concrete'), hidden=True)), turning=False)
    trench_level = _starter_level('easy-block', 'Fill the trench', 'structure',
        'The ball rolls along the table toward a trench. Set the block down in the trench and stretch its height until its top is level with the tables.',
        trench, [block],
        {'title': 'The ball is in the cup', 'focus': ['ball'],
         'station': {'done_when': {'in_zone': {'part': 'ball', 'at_m': [.89, .34, 0], 'size_m': [.34, .1, .22]}}}},
        [dict(piece='block', x_m=.05, z_m=0, tall_m=.3)], [dict(piece='block', x_m=.05, z_m=0, tall_m=.2)], 4,
        'A block stays exactly where you set it and holds up what rolls over it. Too low leaves a hole; too high makes a wall.',
        53400000)  # 53,352,000 J: 56.2 kg of concrete, rounded up

    # Swing on a rope: an oak beam held out from one post, ending short of a
    # trapdoor whose own weight opens it at the start (nothing is above the
    # marble, so it is set down on the leaf). A string ('tie') pulls but
    # never pushes.
    swing = base('Swing on a rope')
    swing['parts'] = [box('frame post', [.08, 1.4, .08], [.85, .7, 0]),
                      box('frame beam', [.99, .08, .16], [.395, 1.44, 0], 'oak'),
                      box('trapdoor stand', [.08, .75, .08], [-.685, .375, 0]),
                      box('trapdoor leaf', [.2, .04, .3], [-.52, .75, 0], 'oak', False)]
    swing['joints'] = [dict(name='trapdoor hinge', kind='hinge', a='trapdoor stand', b='trapdoor leaf',
                            at_m=[-.62, .75, 0], axis=[0, 0, 1], lower_deg=-90, upper_deg=0, friction_n_m=.01)]
    hung = _starter_row('ring_marble', dict(x_m=number('Position along (m)', -.6, -.2, -.25),
                                            z_m=number('Position across (m)', -.4, .4, 0)), turning=False,
                        sandbox_builder=True, tie_on=RING_TIE)
    string = dict(piece='link', count=1, cost=0, turning=False, across=False, attach=True, knobs=dict(
        kind=choice('Joined by', ['string'], 'string'),
        a={'part': True, 'default': '', 'label': 'one part'},
        b={'part': True, 'default': '', 'label': 'the other part'},
        at_m={'point': True, 'label': 'where'},
        at_b_m={'point': True, 'needed': False, 'label': "the string's other end"}),
        # A visible tie ring under the beam's end: a tap on the beam within
        # 20 cm of it ties there. Placement help only; the engine decides the swing.
        tie_points=[{'part': 'frame beam', 'at_m': [0, 1.4, 0], 'snap_m': .2, 'label': 'tie ring'}])
    # The top bar of the ring marble's ring, the marble resting on the leaf:
    # ball centre .792 (leaf top .77, radius .02, set-down gap .002), ring
    # centre .835, top bar .855.
    on_leaf = [-.5, .855, 0]
    swing_level = _starter_level('easy-rope', 'Swing on a rope', 'rope tension',
        'Set the ring marble on the trapdoor, which drops open when you start. Then add the string: tap the gold tie ring at the end of the beam and drag the string\'s loose end onto the marble\'s ring, so it swings up into the green zone.',
        swing, [hung, string],
        {'title': 'The marble swings into the zone', 'focus': ['your ring_marble 1'], 'needs': 'Place the ring marble first.',
         'station': {'done_when': {'in_zone': {'part': 'your ring_marble 1', 'at_m': [.42, .74, 0], 'size_m': [.16, .12, .2]}}}},
        [dict(piece='ring_marble', x_m=-.5, z_m=0),
         dict(piece='link', kind='string', a='frame beam', b='your ring_marble 1 ring', at_m=[0, 1.4, 0], at_b_m=on_leaf)],
        [dict(piece='ring_marble', x_m=-.5, z_m=0),
         dict(piece='link', kind='string', a='trapdoor stand', b='your ring_marble 1 ring', at_m=[-.645, .1, 0], at_b_m=on_leaf)], 3,
        'A string pulls but never pushes. Tied high and to one side, the falling marble swings around the knot; tied low, the string goes slack and the marble just drops.',
        7060000)  # 7,052,260 J: the 0.282 kg iron ring marble, rounded up; a string has no modelled mass
    return [roll_level, trench_level, swing_level]


STARTER_LEVELS = _starter_levels()
EASY_LEVELS.extend(STARTER_LEVELS)
