"""Placement assistance from compiled geometry; never a simulation response.

Distances are metres. A fit is an editor suggestion, not a prediction of a
cut, reflection or successful run. Old explicit port-joining stays separate.
"""
import math

import machine_world as mw

CAPTURE_M = .08
RELEASE_M = .11


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def feature(name, label, at, direction=None, **extra):
    return dict(part=name, label=label, at=[round(v, 6) for v in at],
                **({'dir': direction} if direction is not None else {}), **extra)


def features(compiled):
    """Working points use the actual declared faces, axes and blade edges."""
    parts = {p['name']: p for p in compiled['parts']}
    special = {}
    light = compiled.get('light') or {}
    for name in light.get('mirrors', []):
        p = parts[name]
        special[name] = feature(name, 'mirror center', p['at_m'], mw._axes(p)[0])
    for lens in light.get('lenses', []):
        special[lens['on']] = feature(lens['on'], 'lens center', lens['at_m'], mw._unit(lens['axis']))
    for panel in compiled.get('solar_panels', []):
        p = parts[panel['part']]
        special[p['name']] = feature(p['name'], 'collecting face', p['at_m'], mw._unit(panel['normal']))
    for blade in compiled.get('blades', []):
        at = [(a+b)/2 for a, b in zip(blade['heel_m'], blade['tip_m'])]
        row = feature(blade['part'], 'cutting edge', at, blade['facing'])
        # Follow fixed attachments to the driving hinge. The lowest point of
        # the edge's circle is kinematic geometry, not an invented trajectory.
        connected = {blade['part']}
        for _ in range(len(compiled.get('joints', []))):
            for j in compiled.get('joints', []):
                if j['kind'] == 'fix' and (j['a'] in connected or j['b'] in connected):
                    connected.update((j['a'], j['b']))
        hinge = next((j for j in compiled.get('joints', []) if j['kind']=='hinge' and j['b'] in connected), None)
        if hinge:
            axis = mw._unit(hinge['axis'])
            offset = [at[i]-hinge['at_m'][i] for i in range(3)]
            along = dot(offset, axis)
            radial = [offset[i]-along*axis[i] for i in range(3)]
            down = [0, -1, 0]
            lowest = mw._unit([down[i]-dot(down, axis)*axis[i] for i in range(3)])
            if lowest:
                radius = math.hypot(*radial)
                low = [hinge['at_m'][i]+along*axis[i]+radius*lowest[i] for i in range(3)]
                torque = dot(cross(radial, down), axis)
                tangent = [v*(1 if torque>=0 else -1) for v in cross(axis, lowest)] if abs(torque)>1e-9 else None
                row = feature(blade['part'], 'lowest cutting-edge sweep', low,
                              tangent, kinematic=True, edge_at=at)
        special[blade['part']] = row
    out = list(special.values())
    for p in compiled['parts']:
        if p['name'] in special:
            continue
        out.append(feature(p['name'], 'center', p['at_m']))
        for component_index, solid in enumerate(mw.solids_of(p)):
            if p['shape']=='compound' and p['parts'][component_index]['shape']!='box':
                continue  # A cylinder's bounding box is not a flat support.
            if solid['shape'] != 'box':
                continue
            size, axes = solid['size_m'], mw._axes(solid)
            # Thin upward-facing boards/decks. A pillar is not a track.
            if size[1] >= min(size[0], size[2]) or axes[1][1] < .65:
                continue
            top = [solid['at_m'][i]+size[1]/2*axes[1][i] for i in range(3)]
            out.append(feature(p['name'], 'top surface', top, axes[1],
                               surface=dict(center=top, axes=axes, size=size)))
    for d in compiled.get('electrical', {}).get('devices', []):
        for key, at in d.get('terminals', {}).items():
            out.append(feature(d['part'], key+' terminal', at))
    return out


def guide(compiled, mine, port_rows=(), prefer_exit=False):
    all_points = features(compiled)
    own = [f for f in all_points if f['part'] in mine]
    primary = next((f for f in own if f['label'] in ('lowest cutting-edge sweep', 'cutting edge',
                   'mirror center', 'lens center', 'collecting face')), None)
    if primary is None and port_rows:
        port = next((p for p in port_rows if p['kind']==('out' if prefer_exit else 'in')), port_rows[0])
        primary = feature(port['name'], port['port'], port['at'], port['dir'])
    if primary is None:
        primary = next((f for f in own if f['label']=='top surface'), own[0] if own else None)
    return dict(primary=primary, targets=[f for f in all_points if f['part'] not in mine])


def seat_candidates(p, part, compiled):
    """Center a ball on a nearby board lane, clear of its ends and edges.

    Surface placement lets the existing compiler find support height. An
    explicitly airborne ball must also be near the candidate in height.
    """
    radius = p.get('diameter_m', .04)/2
    current = part['at_m']
    out = []
    for f in features(compiled):
        surface = f.get('surface')
        if not surface or f['part'] == part['name']:
            continue
        axes, size, center = surface['axes'], surface['size'], surface['center']
        length_axis = 0 if size[0] >= size[2] else 2
        side_axis = 2 if length_axis == 0 else 0
        if size[side_axis] < 2*radius+.01 or size[length_axis] < 2*radius+.01:
            continue
        forward, normal = axes[length_axis], axes[1]
        # Horizontal pointer motion -> lane coordinate, preserving slope.
        horizontal2 = forward[0]**2+forward[2]**2
        if horizontal2 < .1:
            continue
        t = sum((current[i]-center[i]-(radius+.002)*normal[i])*forward[i] for i in (0, 2))/horizontal2
        limit = size[length_axis]/2-radius-.005
        t = max(-limit, min(limit, t))
        at = [center[i]+t*forward[i]+(radius+.002)*normal[i] for i in range(3)]
        horizontal = math.hypot(at[0]-current[0], at[2]-current[2])
        # On-surface pieces can settle onto a board, but cannot be attracted
        # across a large void or onto the roof of a different storey.
        vertical = abs(at[1]-current[1])
        distance = math.hypot(horizontal, vertical)
        if distance > RELEASE_M:
            continue
        out.append(dict(distance=distance, knobs=dict(x_m=round(at[0],4), z_m=round(at[2],4),
                         **({'height_m':round(at[1],4)} if p.get('placement')=='at height' else {})),
                        to=f['part'], port='track center' if size[length_axis]>size[side_axis]*2 else 'top surface',
                        at=at))
    return out
