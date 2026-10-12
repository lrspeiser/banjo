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
    x, z = _position(k)
    height = k.get('height_m', .65)
    rest = k.get('rest_m', .5)
    # Linear force element, not a material model for the drawn coil.
    side = .12
    base = box(name + ' base', [.3, .08, .3], [x, .04, z])
    load = box(name + ' load', [side] * 3, [x, height, z], k.get('material', 'oak'), False)
    guide = box(name + ' guide', [.06, height + .2, .06], [x, (height + .2) / 2, z + .18])
    return {'parts': [base, load, guide], 'joints': [
        {'name': name + ' spring', 'kind': 'spring', 'a': base['name'], 'b': load['name'],
         'at_m': [x, .08, z], 'at_b_m': [x, height, z], 'rest_m': rest,
         'stiffness_n_m': k.get('stiffness_n_m', 200), 'damping_n_s_m': k.get('damping_n_s_m', 6)},
        {'name': name + ' slide', 'kind': 'slide', 'a': guide['name'], 'b': load['name'],
         'at_m': [x, height, z], 'axis': [0, 1, 0], 'lower_m': .145 - height,
         'upper_m': .4, 'friction_n': 0}]}


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


PIECES = {'knife': knife, 'mirror': mirror, 'lens': lens, 'solar': solar,
          'tackle': tackle, 'weight': weight, 'spring': spring, 'gears': gears}


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
    tray('spring', 'Spring and guided load', {'height_m': number('Starting height (m)', .4, .9, .65),
         'rest_m': number('Relaxed length (m)', .2, .7, .5),
         'stiffness_n_m': number('Stiffness (N/m)', 50, 1000, 200, 10),
         'damping_n_s_m': number('Internal damping (N s/m)', 0, 30, 6, 1),
         'material': choice('Load material', ['oak', 'glass', 'iron'], 'oak')}, turning=False),
    tray('gears', 'Gear pair', {'height_m': number('Axle height (m)', .35, .8, .4),
         'teeth_a': choice('Input teeth', [12, 18, 24], 12),
         'teeth_b': choice('Output teeth', [12, 18, 24], 24),
         'friction_n_m': number('Bearing friction (N m)', 0, .1, .02, .01),
         'drive': choice('Included battery drive', ['off', 'forward', 'reverse'], 'off')}, turning=False),
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
         'base': bounce, 'placements': [{'piece': 'spring'}]},
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
