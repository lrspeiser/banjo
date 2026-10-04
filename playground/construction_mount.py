"""Fastening a placed thing to what it stands on, and undoing it.

A thing set down on a support (a foundation pad, a table) only rests there: it
slides off when the support tips and stays behind when the support is moved.
Fastening joins the two with a native fixing (LiveWorld::fix), rated the way
a product's own bonded joint is (mcp/product_joints.py): the weaker material's
tensile and shear strength over the area where the thing's foot meets the
support's top. Joint efficiency is 1.0 by the owner's call of 2026-09-19
(mcp/joint_efficiency.py), so a fastening holds as the weaker material does.

The fixing is a joint in the running room, so it is saved with the room and
breaks in the room when a load beyond its rating pulls or shears it. Nothing
here moves either body. Not modelled: the fastener itself (bolts, glue line),
bending and twisting at the joint (the engine checks tension and shear only).
"""
import math

from mcp import engine_materials

# Parts whose bottoms are this close to the lowest are its foot.
FOOT_M = .005
# The foot must be this close to the support's top to be standing on it.
TOUCH_M = .02


def _bodies(app):
    return {b['name']: b for b in (app.live.session.state or {}).get('bodies', [])}


def _footprint(body, low_only):
    """World x/z extents and the material of a body's lowest parts (its foot),
    or of its top when low_only is False: (x0, x1, z0, z1, y, material)."""
    import placement
    q = body.get('orientation_wxyz') or [1, 0, 0, 0]
    at = body['position_m']
    parts = body.get('rigid_parts_local') or [None]
    rows = []
    for part in parts:
        if part is None:
            spans = [placement._span(body, q, k) for k in range(3)]
            material = body.get('material') or ''
        else:
            spans = [placement._part_span(part, q, k) for k in range(3)]
            material = part.get('material') or body.get('material') or ''
        rows.append(([at[k] + spans[k][0] for k in range(3)], [at[k] + spans[k][1] for k in range(3)], material))
    if low_only:
        y = min(lo[1] for lo, _, _ in rows)
        rows = [r for r in rows if r[0][1] - y < FOOT_M]
    else:
        y = max(hi[1] for _, hi, _ in rows)
        rows = [r for r in rows if y - r[1][1] < FOOT_M]
    return (min(r[0][0] for r in rows), max(r[1][0] for r in rows),
            min(r[0][2] for r in rows), max(r[1][2] for r in rows), y, rows[0][2])


def rating(app, item, support):
    """What a fastening of item to support could carry, from the contact."""
    bodies = _bodies(app)
    a, b = bodies.get(item), bodies.get(support)
    if not a or not b:
        raise ValueError('Both the item and what it stands on must be in the world')
    if b.get('parked') or a.get('parked'):
        raise ValueError('Put both in the world before fastening them')
    fx0, fx1, fz0, fz1, foot_y, foot_material = _footprint(a, True)
    tx0, tx1, tz0, tz1, top_y, top_material = _footprint(b, False)
    if abs(foot_y - top_y) > TOUCH_M:
        raise ValueError(f'The {item} is not standing on the {support}: its foot is '
                         f'{abs(foot_y - top_y) * 100:.0f} cm from the top')
    across = max(0.0, min(fx1, tx1) - max(fx0, tx0))
    deep = max(0.0, min(fz1, tz1) - max(fz0, tz0))
    area = across * deep
    if area <= 0:
        raise ValueError(f'The {item} does not touch the {support}')
    try:
        ma, mb = engine_materials.mechanics(foot_material), engine_materials.mechanics(top_material)
    except KeyError as unknown:
        raise ValueError(f'No strength is known for {unknown}') from None
    tensile = min(ma['tensile_strength_pa'], mb['tensile_strength_pa'])
    shear = min(ma['shear_strength_pa'], mb['shear_strength_pa'])
    weaker = foot_material if ma['tensile_strength_pa'] <= mb['tensile_strength_pa'] else top_material
    return {'area_m2': round(area, 6), 'holds_tension_n': tensile * area, 'holds_shear_n': shear * area,
            'governed_by': engine_materials.canonical(weaker),
            'at_m': [(max(fx0, tx0) + min(fx1, tx1)) / 2, (foot_y + top_y) / 2, (max(fz0, tz0) + min(fz1, tz1)) / 2],
            'not_modelled': ['the fastener itself: bolts, screws or a glue line',
                             'bending and twisting at the joint; the engine checks pull and shear only']}


def fasten(app, item, support):
    rated = rating(app, item, support)
    reply = app.live.act({'session': app.live.session.id, 'op': 'fix', 'a': support, 'b': item,
                          'at': rated['at_m'], 'axis': [0, 1, 0],
                          'holds_tension_n': rated['holds_tension_n'], 'holds_shear_n': rated['holds_shear_n']})
    joint = reply.get('joint')
    if not joint:
        raise ValueError(f'The {item} could not be fastened to the {support}')
    return {'joint': int(joint), 'to': support, **{k: rated[k] for k in
            ('area_m2', 'holds_tension_n', 'holds_shear_n', 'governed_by', 'not_modelled')}}


def holding(app, fastened):
    """Whether a recorded fastening is still a joint in the room."""
    joints = (app.live.session.state or {}).get('joints') or []
    return any(j.get('id') == fastened.get('joint') and j.get('attached', True) for j in joints)


def unfasten(app, fastened):
    app.live.act({'session': app.live.session.id, 'op': 'unhinge', 'joint': int(fastened['joint'])})
