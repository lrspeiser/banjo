"""A loose, insulated battery pack and a holder with actual metal contacts.

Contacts are separate rigid bodies, not labels on the housing. Four possible
cap/pad paths permit reversed polarity; geometric touching selects the paths.
Resistance is the existing fixed contact idealization, not a pressure law.
"""
import math

HOLDER_NAME = 'battery holder'
HOUSING_SIZE = [.20, .08, .10]
CAP_SIZE = [.04, .04, .08]
SPACER_SIZE = [.04, .04, .08]


def box(name, at, size, material, fixed):
    return dict(name=name, shape='box', at_m=list(at), size_m=list(size),
                material=material, fixed=fixed)


def holder_metadata(x=-.5, z=0, name=HOLDER_NAME):
    return dict(name=name, x_m=x, z_m=z,
                terminal_parts={p: name + ' ' + p + ' pad' for p in ('plus', 'minus')})


def holder(x=-.5, z=0):
    """Grounded insulating seat; its pads are independent iron collision bodies."""
    meta = holder_metadata(x, z)
    # Wire jacks leave the front of each metal pad. The top face must remain
    # clear for the falling pack's metal caps to touch it; a cord across that
    # landing face would be crushed/pulled out by the pack.
    terminals = {p: [x + sign * .08, .10, z + .055] for p, sign in (('plus', -1), ('minus', 1))}
    return {'parts': [box(HOLDER_NAME + ' base', [x, .04, z], [.40, .08, .28], 'concrete', True)] +
                     [box(meta['terminal_parts'][p], [at[0], .10, z], [.06, .04, .10], 'iron', True)
                      for p, at in terminals.items()],
            'electrical': {'devices': [dict(name=HOLDER_NAME, kind='socket', part=HOLDER_NAME + ' base',
                terminals=terminals, terminal_parts=meta['terminal_parts'])]}}


def battery(name, k, ctx):
    """Five loose material bodies joined as one pack, with no automatic wire."""
    x, z, y = k.get('x_m', 0), k.get('z_m', 0), k.get('height_m', .40)
    material = k.get('housing_material', 'iron')
    if material not in ('glass', 'oak', 'iron'):
        raise ValueError('Contact pack housing material must be glass, oak or iron.')
    housing = name + ' housing'
    parts = [box(housing, [x, y, z], HOUSING_SIZE, material, False)]
    joints, terminal_parts, terminals = [], {}, {}
    yaw = float(k.get('yaw_deg', 0))
    radians = math.radians(yaw)
    for pole, sign in (('plus', -1), ('minus', 1)):
        spacer, cap = name + ' ' + pole + ' insulator', name + ' ' + pole + ' cap'
        px, pz = x + sign * .08 * math.cos(radians), z - sign * .08 * math.sin(radians)
        parts.extend([box(spacer, [px, y - .06, pz], SPACER_SIZE, 'glass', False),
                      box(cap, [px, y - .10, pz], CAP_SIZE, 'iron', False)])
        for a, b, at_y, tag in ((housing, spacer, y - .04, 'insulator'),
                                (spacer, cap, y - .08, 'cap')):
            joints.append(dict(name=name + ' ' + pole + ' ' + tag + ' fixing', kind='fix', a=a, b=b,
                at_m=[px, at_y, pz], axis=[0, 1, 0], holds_tension_n=100000, holds_shear_n=100000))
        terminal_parts[pole] = cap
        terminals[pole] = [px, y - .12, pz]
    if yaw:
        for p in parts: p['turn_deg'] = [0, yaw, 0]
    capacity = k.get('capacity_j', 1000)
    fragment = {'parts': parts, 'joints': joints,
        'batteries': [dict(name=name + ' battery', **{'in': housing}, capacity_j=capacity,
            charge_j=capacity * k.get('charge_percent', 100) / 100,
            voltage_v=k.get('voltage_v', 12), max_power_w=k.get('max_power_w', 200))],
        'electrical': {'devices': [dict(name=name, kind='battery', part=housing,
            battery=name + ' battery', terminals=terminals, terminal_parts=terminal_parts)], 'contacts': []}}
    metadata = (ctx or {}).get('tray', {}).get('contact_holder')
    if metadata:
        if not isinstance(metadata, dict):
            raise ValueError('contact_holder must describe a holder and its physical pads.')
        target = metadata.get('name', HOLDER_NAME)
        pads = metadata.get('terminal_parts', {p: target + ' ' + p + ' pad' for p in ('plus', 'minus')})
        for cap_pole in ('plus', 'minus'):
            for pad_pole in ('plus', 'minus'):
                fragment['electrical']['contacts'].append(dict(
                    name=name + ' ' + cap_pole + ' to ' + target + ' ' + pad_pole,
                    a=name + ':' + cap_pole, b=target + ':' + pad_pole,
                    touch=[terminal_parts[cap_pole], pads[pad_pole]], resistance_ohm=.001))
    return fragment
