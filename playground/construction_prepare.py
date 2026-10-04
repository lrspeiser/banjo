"""Preparing ground for a thing that will not stand: which ground to dig.

When no supported spot is in reach, the build guide marks a patch of ground
in front of the player the size of the held thing, reads the ground under it
and says which squares stand proud of the lowest one, and by how much. The
player digs those squares with an ordinary digging tool (tool_use), and the
earth they dig goes into their carried load like any other digging.

Nothing here moves earth, and a prepared patch is not a promise: every view
reads the ground again, and the site is still checked by the native placement
trial when the player asks for a spot (construction_projects.suggest).
"""
import math

# What may stay above the level: the native stand trial accepts up to 10
# degrees of tilt, and 2 cm over a 25 cm square is under 5.
LEVEL_TOLERANCE_M = .02
# Ground round the thing as well, so its edges come down on dug ground.
MARGIN_M = .1
# The square size when the room says no ground grid.
SQUARE_M = .25
MOST_SQUARES = 64
# More than this from the highest to the lowest square is a hillside, not
# a patch to level by hand.
MOST_CUT_M = .45
# The patch's middle, ahead of the feet: beyond a digging tool's least reach
# from where the player stands to dig it, and within hand reach to place.
AHEAD_M = 1.1


def footprint(app, name):
    """The held thing's width and depth on the ground, generously: the widest
    horizontal reach of any of its parts from their joint middle, both ways."""
    import placement
    bodies = {b['name']: b for b in (app.live.session.state or {}).get('bodies', [])}
    parts = [bodies[n] for n in placement.own_parts(app, name) if n in bodies] or [bodies[name]]
    xs, zs = [], []
    for part in parts:
        q = part.get('orientation_wxyz', [1, 0, 0, 0])
        for axis, store in ((0, xs), (2, zs)):
            low, high = placement._span(part, q, axis)
            store += [part['position_m'][axis] + low, part['position_m'][axis] + high]
    width, depth = max(xs) - min(xs), max(zs) - min(zs)
    # It is set down square to the player, whichever way it is held now.
    side = max(width, depth)
    return [side, side]


def grid(app):
    """Where the ground's cells are: one height per cell, at its middle. Read
    once per running room; the grid does not move while it runs."""
    session = app.live.session
    known = getattr(session, 'ground_grid', None)
    if known is None:
        report = (app.live.act({'session': session.id, 'op': 'environment'}) or {}).get('environment') or {}
        got = report.get('grid') or {}
        known = {'x0_m': float(got['x0_m']), 'z0_m': float(got['z0_m']), 'cell_m': float(got['cell_m']),
                 'nx': int(got['nx']), 'nz': int(got['nz'])} if got else None
        try:
            session.ground_grid = known
        except AttributeError:
            pass
    return known


def plan(app, name, person):
    """The patch in front of the person, sized to the held thing."""
    feet, face = person['standing_m'], person['facing']
    flat = math.hypot(face[0], face[2]) or 1.0
    ahead = [face[0] / flat, face[2] / flat]
    centre = [feet[0] + ahead[0] * AHEAD_M, feet[2] + ahead[1] * AHEAD_M]
    size = footprint(app, name)
    return {'centre_m': [round(v, 4) for v in centre], 'ahead': [round(v, 6) for v in ahead],
            'size_m': [round(v + 2 * MARGIN_M, 4) for v in size], 'grid': grid(app)}


def squares(saved):
    """The ground's own cells under the patch: a marked square is a cell, so
    digging where it is drawn lowers exactly the height that was read."""
    across, along = saved['size_m']
    g = saved.get('grid')
    if not g:
        # No grid said (a flat floor): squares of the coarse cell size.
        g = {'x0_m': -(1 << 20) * SQUARE_M, 'z0_m': -(1 << 20) * SQUARE_M, 'cell_m': SQUARE_M,
             'nx': 1 << 21, 'nz': 1 << 21}
    h = g['cell_m']
    half = max(across, along) / 2
    cx, cz = saved['centre_m']
    lo = [math.ceil((cx - half - g['x0_m']) / h - .5), math.ceil((cz - half - g['z0_m']) / h - .5)]
    hi = [math.floor((cx + half - g['x0_m']) / h + .5), math.floor((cz + half - g['z0_m']) / h + .5)]
    lo = [max(0, lo[0]), max(0, lo[1])]
    hi = [min(g['nx'] - 1, hi[0]), min(g['nz'] - 1, hi[1])]
    cells = [(i, j) for i in range(lo[0], hi[0] + 1) for j in range(lo[1], hi[1] + 1)]
    if not cells:
        i, j = round((cx - g['x0_m']) / h), round((cz - g['z0_m']) / h)
        cells = [(i, j)]
    # The nearest to the middle first, when the thing is too big to mark all.
    cells.sort(key=lambda c: math.hypot(g['x0_m'] + c[0] * h - cx, g['z0_m'] + c[1] * h - cz))
    for i, j in cells[:MOST_SQUARES]:
        yield [g['x0_m'] + i * h, g['z0_m'] + j * h], [h, h]


def read(app, saved):
    """The patch as the ground is now: each square's height, what to dig."""
    rows = []
    for at, size in squares(saved):
        got = (app.live.act({'session': app.live.session.id, 'op': 'survey', 'at': at}) or {}).get('survey') or {}
        if not got.get('on_the_ground'):
            return {'fits': False, 'why': 'Part of that patch is off the ground.', 'squares': []}
        ground = float(got['ground_m'])
        runs = got.get('runs') or []
        rows.append({'at_m': [round(at[0], 4), round(ground, 4), round(at[1], 4)],
                     'size_m': [round(v, 4) for v in size], 'ground_m': ground,
                     'rock_top_m': float(got.get('rock_top_m', ground - 1.0)),
                     'material': runs[-1]['material'] if runs else got.get('surface') or 'ground',
                     'wet': float((got.get('water') or {}).get('depth_m', 0)) > .005})
    level = min(r['ground_m'] for r in rows)
    rise = max(r['ground_m'] for r in rows) - level
    marked, volume = [], 0.0
    for r in rows:
        cut = r['ground_m'] - level
        if cut <= LEVEL_TOLERANCE_M:
            continue
        volume += cut * r['size_m'][0] * r['size_m'][1]
        marked.append({'at_m': r['at_m'], 'size_m': r['size_m'], 'dig_m': round(cut, 3),
                       'material': r['material'],
                       'rock': r['rock_top_m'] > level + LEVEL_TOLERANCE_M,
                       'wet': r['wet']})
    out = {'level_m': round(level, 4), 'rise_m': round(rise, 3), 'squares': marked,
           'dig_m3': round(volume, 4), 'size_m': saved['size_m'], 'centre_m': saved['centre_m'],
           'ahead': saved['ahead'],
           'done': not marked}
    if rise > MOST_CUT_M:
        out['why'] = (f'The ground falls {rise:.2f} m across that patch: too much to level by hand. '
                      'Try flatter ground, or face along the slope.')
    elif any(s['wet'] for s in marked):
        out['why'] = 'Part of that patch is under water; dig somewhere dry.'
    elif any(s['rock'] for s in marked):
        out['why'] = 'Rock is near the surface there: a pick will be needed, and a hard one.'
    return out


def instruction(read_out):
    if read_out['done']:
        return 'The marked ground is level. Find a supported spot to check it.'
    n = len(read_out['squares'])
    deepest = max(s['dig_m'] for s in read_out['squares'])
    return (f'Dig the {n} marked square{"s" if n != 1 else ""} down to the lowest one '
            f'(at most {deepest * 100:.0f} cm, about {read_out["dig_m3"] * 1000:.0f} litres of earth) '
            'with a shovel or pick, then find a supported spot.')
