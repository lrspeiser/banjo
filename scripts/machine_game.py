"""Puzzles on the machine: a level, a tray of pieces, a goal the engine checks.

A level is a machine (banjo.machine.v1) that is fixed -- the player cannot
move it -- plus a goal, a time limit, and a TRAY: the pieces the player may
add, each with a cost and a few knobs (where it goes, how high, how much
powder). The player's placements are composed into the level's machine and
the engine runs the whole thing; nothing about the outcome is decided here.

Scoring, from what the engine measured:
  goal     the goal happened within the time limit
  budget   the pieces cost no more than the level's par
  style    the chain used at least the level's number of different pieces

Reliability: a real chain of events is fragile. `trial` runs the same machine
several times with every loose part nudged by a millimetre or two, and says
in how many the goal happened -- which a player can try to raise.

Levels live in client/voxel-lab/levels.json.
"""
import copy
import json
import math
import random
from pathlib import Path

import machine_world as mw

ROOT = Path(__file__).resolve().parents[1]
LEVELS_PATH = ROOT / 'client/voxel-lab/levels.json'


# Every piece can be moved across (z) and turned however a person turns a
# thing in their hands -- about the vertical, tipped end up, rolled about its
# length -- unless its level says "turning": false. These knobs are added to
# every tray. They cost nothing, and the engine's search leaves them where
# the player put them ("free").
FREE_KNOBS = {
    'z_m': {'min': -1.0, 'max': 1.0, 'step': 0.01, 'default': 0.0, 'label': 'across (z, m)', 'free': True},
    'yaw_deg': {'min': -180, 'max': 180, 'step': 1, 'default': 0, 'label': 'turn', 'free': True, 'turning': True},
    'pitch_deg': {'min': -180, 'max': 180, 'step': 1, 'default': 0, 'label': 'tip', 'free': True, 'turning': True},
    'roll_deg': {'min': -180, 'max': 180, 'step': 1, 'default': 0, 'label': 'roll', 'free': True, 'turning': True},
}


def load_levels():
    levels = json.loads(LEVELS_PATH.read_text(encoding='utf-8'))['levels']
    for level in levels:
        for t in level['tray']:
            # A piece whose own knob already turns it about the vertical (a
            # mirror's angle_deg) keeps that one as its turn.
            own_turn = any(r.get('turning') for r in t['knobs'].values())
            for key, rule in FREE_KNOBS.items():
                if rule.get('turning') and (not level.get('turning', True) or t.get('turning') is False
                                            or (key == 'yaw_deg' and own_turn)):
                    continue
                t['knobs'].setdefault(key, dict(rule))
    return levels


def level_by_id(level_id):
    for level in load_levels():
        if level['id'] == level_id:
            return level
    raise ValueError(f'There is no level called {level_id!s}')


# ---- the pieces ---------------------------------------------------------------
#
# Each piece type turns a placement's knobs into the machine's own kits and
# parts. The knobs a level allows, and their ranges, are in the level's tray;
# every value is checked against them before anything is built.

def set_down_height(parts, x0, x1, z0, z1):
    """The top of the highest thing under a footprint (x0..x1, z0..z1):
    where a piece set down there comes to rest first. The ground is 0."""
    top = 0.0
    for p in parts:
        if p['shape'] == 'sphere':
            r = 0.5 * p['size_m'][0]
            ext = [r, r, r]
        else:
            axes, half = mw._axes(p), mw._half(p)
            ext = [sum(abs(axes[j][i]) * half[j] for j in range(3)) for i in range(3)]
        c = p['at_m']
        if c[0] + ext[0] <= x0 or c[0] - ext[0] >= x1 or c[2] + ext[2] <= z0 or c[2] - ext[2] >= z1:
            continue
        top = max(top, c[1] + ext[1])
    return top


def _turn(k):
    """The player's turn of a piece (the free knobs): yaw about the vertical,
    pitch its +x end up, roll about its length. None when it is not turned."""
    angles = [k.get('yaw_deg', 0.0), k.get('pitch_deg', 0.0), k.get('roll_deg', 0.0)]
    return angles if any(angles) else None


def _turned_kit(kit, k, about):
    """A kit turned as the player turned the piece, about `about` (the point
    its knobs put where they say), then lifted to stand on the ground if the
    turn took any of it into the ground."""
    angles = _turn(k)
    if angles:
        kit['turned'] = {'yaw_deg': angles[0], 'pitch_deg': angles[1], 'roll_deg': angles[2],
                         'about_m': list(about), 'clear_ground': True}
    return kit


def _plank(name, k, ctx):
    """A loose plank, cut to length_m and set down with its middle at x_m:
    turned as the player turned it, then lowered until it meets the first
    thing under it, and from then on it is gravity and contact that hold it.
    Nothing about it is bolted."""
    length, thick, width = k['length_m'], 0.02, k.get('width_m', 0.3)
    x, z = k['x_m'], k.get('z_m', 0.0)
    angles = _turn(k) or [0.0, 0.0, 0.0]
    part = {'name': name, 'shape': 'box', 'material': k.get('material', 'oak'),
            'size_m': [round(length, 4), thick, width], 'at_m': [round(x, 4), 0.0, z],
            'turn_deg': mw.turn_of(mw.heading(*angles)), 'fixed': False}
    axes, half = mw._axes(part), mw._half(part)
    ext = [sum(abs(axes[j][i]) * half[j] for j in range(3)) for i in range(3)]
    rest = set_down_height(ctx['parts'], x - ext[0], x + ext[0], z - ext[2], z + ext[2])
    part['at_m'][1] = round(rest + ext[1] + 0.002, 4)
    return {'parts': [part]}


def _knife(name, k, ctx=None):
    pivot = [k['x_m'], k['pivot_height_m'], k.get('z_m', 0.0)]
    return {'kits': [_turned_kit({'kit': 'knife_pendulum', 'name': name, 'pivot_m': pivot, 'arm_m': k['arm_m'],
                                  'swing_toward': k.get('swing_toward', '+x'), 'weight_kg': k.get('weight_kg', 0.0),
                                  'edge_radius_m': k.get('edge_radius_m', 0.0002)}, k, pivot)]}


def _cannon(name, k, ctx=None):
    muzzle = [k['x_m'], k['bore_height_m'], k.get('z_m', 0.0)]
    kit = {'kit': 'cannon', 'name': name, 'at_m': muzzle,
           'toward': k.get('toward', '+x'), 'powder_g': k['powder_g'],
           'ball': {'diameter_m': k.get('ball_diameter_m', 0.08), 'material': k.get('ball_material', 'iron')}}
    if k.get('fire_at_s') is not None:
        kit['fire_at_s'] = k['fire_at_s']
    return {'kits': [_turned_kit(kit, k, muzzle)]}


def _steam(name, k, ctx=None):
    base = [k['x_m'], 0.0, k.get('z_m', 0.0)]
    return {'kits': [_turned_kit({'kit': 'steam_engine', 'name': name, 'at_m': base,
                                  'heat_w': k['heat_kw'] * 1000.0, 'boiler_side': k.get('boiler_side', '-x')},
                                 k, base)]}


def _ramp(name, k, ctx=None):
    """A ramp with a ball at its top, running toward +x: its top at
    (x_m, top_height_m), down to its foot `run_m` further on at foot_height_m.
    Turned, it turns about its top."""
    top = [k['x_m'], k['top_height_m'], k.get('z_m', 0.0)]
    return {'kits': [_turned_kit({'kit': 'ramp', 'name': name, 'top_m': top,
                                  'bottom_m': [k['x_m'] + k['run_m'], k['foot_height_m'], k.get('z_m', 0.0)],
                                  'width_m': 0.12, 'ball': {'material': k.get('ball_material', 'iron'),
                                                            'diameter_m': 0.08, 'name': name + ' ball'}},
                                 k, top)]}


def _mirror(name, k, ctx=None):
    """A polished aluminium mirror on its own stand, standing upright at
    (x_m, z_m) and turned angle_deg about the vertical: at 0 it faces along
    x. Tipped (pitch), it faces up or down. It reflects what light reaches
    it; where the light goes is the engine's."""
    height = k.get('height_m', 0.575)
    angles = _turn(k) or [0.0, 0.0, 0.0]
    turn = mw.turn_of(mw.heading(angles[0] + k['angle_deg'], angles[1], angles[2]))
    return {'parts': [{'name': name, 'shape': 'box', 'material': 'aluminum', 'size_m': [0.02, 0.2, 0.2],
                       'at_m': [k['x_m'], height, k['z_m']], 'turn_deg': turn, 'fixed': True}],
            'mirrors': [name]}


def _solar(name, k, ctx):
    """A solar panel: a glass plate half a metre square, bolted on a post at
    (x_m, height_m, z_m) and wired to the level's battery (the tray's
    "battery"). Flat, it faces up; turned and tipped, it faces wherever it
    is turned. What it gives is the sunlight falling on its face -- less the
    more slant the sun meets it at, none in shadow -- a fifth of it stored."""
    x, h, z = k['x_m'], k['height_m'], k.get('z_m', 0.0)
    m = mw.heading(*(_turn(k) or [0.0, 0.0, 0.0]))
    plate = {'name': name, 'shape': 'box', 'material': 'glass', 'size_m': [0.5, 0.02, 0.5], 'at_m': [x, h, z],
             'turn_deg': mw.turn_of(m), 'fixed': True}
    post = {'name': name + ' post', 'shape': 'box', 'material': 'concrete', 'size_m': [0.06, round(h - 0.02, 4), 0.06],
            'at_m': [x, round((h - 0.02) / 2, 4), z], 'fixed': True}
    return {'parts': [plate, post],
            'solar_panels': [{'name': name, 'part': name, 'battery': ctx['tray'].get('battery', 'battery'),
                              'normal': [round(v, 9) for v in mw._mat_apply(m, [0.0, 1.0, 0.0])],
                              'area_m2': 0.25, 'efficiency': 0.2}]}


# Counterweights, by mass: a block of whole cells, aluminium for the light
# ones and iron for the heavy (kg -> material, side in metres).
COUNTERWEIGHTS = {2.7: ('aluminum', 0.10), 4.0: ('iron', 0.08), 4.7: ('aluminum', 0.12), 7.4: ('aluminum', 0.14),
                  7.9: ('iron', 0.10), 13.6: ('iron', 0.12), 21.6: ('iron', 0.14)}


def _tackle(name, k, ctx):
    """A block and tackle: a counterweight of counterweight_kg hung at
    (x_m, drop_from_m, z_m) on a rope that runs up over the beam, across, and
    down through `ratio` falls of pulleys to the tray's load. The load rises
    1/ratio as far as the counterweight falls, pulled ratio times as hard:
    it rises only if the counterweight is more than its weight / ratio."""
    material, side = COUNTERWEIGHTS[k['counterweight_kg']]
    x, y, z = k['x_m'], k['drop_from_m'], k.get('z_m', 0.0)
    load = next(p for p in ctx['parts'] if p['name'] == ctx['tray']['load'])
    top = load['at_m'][1] + 0.5 * load['size_m'][1]
    beam = ctx['tray'].get('over_m', 1.95)
    weight = {'name': name, 'shape': 'box', 'material': material, 'size_m': [side] * 3, 'at_m': [x, y, z]}
    rope = {'name': name + ' rope', 'kind': 'pulley', 'a': name, 'b': load['name'],
            'at_m': [x, round(y + 0.5 * side, 4), z], 'at_b_m': [load['at_m'][0], round(top, 4), load['at_m'][2]],
            'over_a_m': [x, beam, z], 'over_b_m': [load['at_m'][0], beam, load['at_m'][2]], 'ratio': k['ratio']}
    return {'parts': [weight], 'joints': [rope]}


def _lens(name, k, ctx):
    """A glass lens on a stand, its middle at (x_m, the tray's height_m, z_m),
    looking along +x until it is turned: convex (it brings a beam to a focus
    about radius_m / 1.05 beyond itself) or concave (it spreads it). Where
    the light goes after it is the engine's, traced through both faces."""
    m = mw.heading(*(_turn(k) or [0.0, 0.0, 0.0]))
    at = [k['x_m'], ctx['tray'].get('height_m', 0.575), k.get('z_m', 0.0)]
    return {'kits': [{'kit': 'lens', 'name': name, 'at_m': at,
                      'axis': [round(v, 9) for v in mw._mat_apply(m, [1.0, 0.0, 0.0])],
                      'shape': k.get('shape', 'convex'), 'radius_m': ctx['tray'].get('radius_m', 0.2),
                      'diameter_m': ctx['tray'].get('diameter_m', 0.1)}]}


PIECES = {'plank': _plank, 'knife': _knife, 'cannon': _cannon, 'steam': _steam, 'ramp': _ramp, 'mirror': _mirror,
          'solar': _solar, 'tackle': _tackle, 'lens': _lens}


class LevelRefused(ValueError):
    def __init__(self, problems):
        super().__init__('; '.join(problems))
        self.problems = problems


def check_placements(level, placements, budget=True):
    """Every placement names a tray piece the level offers, no more of each
    than the tray holds, every knob within its range. Returns the placements
    with defaults filled in and their total cost. budget=False leaves the
    budget to the caller (a piece shown before it is set down)."""
    problems, out, used, cost = [], [], {}, 0.0
    tray = {t['piece']: t for t in level['tray']}
    if not isinstance(placements, list):
        raise LevelRefused(['placements is a list'])
    for i, p in enumerate(placements):
        what = f'piece {i + 1}'
        if not isinstance(p, dict) or p.get('piece') not in tray:
            problems.append(f'{what}: piece is one of {", ".join(tray)}')
            continue
        t = tray[p['piece']]
        used[p['piece']] = used.get(p['piece'], 0) + 1
        if used[p['piece']] > t.get('count', 1):
            problems.append(f'{what}: the tray holds {t.get("count", 1)} {p["piece"]}')
        knobs = {}
        for key, rule in t['knobs'].items():
            value = p.get(key, rule.get('default'))
            if 'choices' in rule:
                if value not in rule['choices']:
                    problems.append(f'{what}: {key} is one of {", ".join(map(str, rule["choices"]))}')
                knobs[key] = value
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                problems.append(f'{what}: {key} must be a number')
                continue
            if not rule['min'] <= value <= rule['max']:
                problems.append(f'{what}: {key} is {rule["min"]} to {rule["max"]}')
            knobs[key] = float(value)
        extra = set(p) - set(t['knobs']) - {'piece'}
        if extra:
            problems.append(f'{what}: {", ".join(sorted(extra))} cannot be set on a {p["piece"]}')
        price = t['cost']
        if 'cost_per' in t:
            # Priced by a knob: a plank by its length, a firebox by its power.
            per = t['cost_per']
            amount = knobs.get(per['knob'], 0)
            price += per['each'] * amount / per['unit']
        cost += price
        out.append(dict(knobs, piece=p['piece'], cost=round(price, 1)))
    if budget and cost > level['budget'] + 1e-9:
        problems.append(f'the pieces cost {cost:.0f}; the budget is {level["budget"]}')
    if problems:
        raise LevelRefused(problems)
    return out, round(cost, 1)


def _assemble(level, placements, lenient=False):
    """The level's machine with the player's pieces built into it, and that
    machine compiled. lenient: as far as it can be, with its problems in it
    (mw.compile_spec), and the budget left unchecked."""
    checked, cost = check_placements(level, placements, budget=not lenient)
    spec = copy.deepcopy(level['machine'])
    spec.setdefault('kits', [])
    spec.setdefault('parts', [])
    spec['title'] = level['title']
    tray = {t['piece']: t for t in level['tray']}
    for i, p in enumerate(checked):
        knobs = {k: v for k, v in p.items() if k not in ('piece', 'cost')}
        # What is there already, for a piece that is set down on it, and
        # what the tray says about it (the battery a panel is wired to).
        ctx = {'parts': mw.compile_spec(dict(spec, stations=[]), lenient=lenient)['parts'], 'tray': tray[p['piece']]}
        made = PIECES[p['piece']](f'your {p["piece"]} {i + 1}', knobs, ctx)
        spec['kits'] += made.get('kits', [])
        spec['parts'] += made.get('parts', [])
        if made.get('joints'):
            spec['joints'] = list(spec.get('joints') or []) + made['joints']
        if made.get('solar_panels'):
            spec['solar_panels'] = list(spec.get('solar_panels') or []) + made['solar_panels']
        if made.get('mirrors'):
            spec.setdefault('light', {}).setdefault('mirrors', [])
            spec['light']['mirrors'] = spec['light']['mirrors'] + made['mirrors']
    return spec, checked, cost, mw.compile_spec(dict(spec, stations=[]), lenient=lenient)


def owner(part):
    """'your plank 1' for every part a player's piece made, else None."""
    bits = part['name'].split(' ')
    return ' '.join(bits[:3]) if bits[0] == 'your' and len(bits) >= 3 else None


def clashes_of(compiled):
    """Nothing of the player's goes into anything else -- not the level, not
    another piece. (The machine itself lets two bolted parts meet; a
    player's bolted mirror stood inside a wall, and a bolted plank inside
    the tables it should have rested on.)"""
    clashes = []
    for a in compiled['parts']:
        if owner(a) is None:
            continue
        for b in compiled['parts']:
            if b is a or owner(b) == owner(a) or (owner(b) is not None and b['name'] < a['name']):
                continue
            depth = max(mw.overlap_depth(sa, sb) for sa in mw.solids_of(a) for sb in mw.solids_of(b))
            if depth > 0.001:
                clashes.append(f'{a["name"]} goes {depth * 1000:.0f} mm into {b["name"]}; move it')
    return clashes


def ghost(level, placements, index):
    """Piece `index` of `placements` as it would be built -- its parts where
    they would be, set down on what is there, turned as it is turned -- and
    why it could not be built there, for the see-through piece the page shows
    before it is set down. Nothing runs in the engine; it takes milliseconds."""
    if not isinstance(placements, list) or not isinstance(index, int) or not 0 <= index < len(placements):
        raise LevelRefused(['index names one of the placements'])
    _, checked, cost, compiled = _assemble(level, placements, lenient=True)
    name = f'your {checked[index]["piece"]} {index + 1}'
    mine = [p for p in compiled['parts'] if owner(p) == name]

    def about_it(problem):
        return name + ' ' in problem + ' ' or name + ':' in problem or name + ';' in problem
    problems = [p for p in compiled['problems'] + clashes_of(compiled) if about_it(p)]
    if cost > level['budget'] + 1e-9:
        problems.append(f'the pieces would cost {cost:.0f}; the budget is {level["budget"]}')
    # A panel: how squarely it faces the sun, and the sunlight that gives
    # on its face if nothing shades it -- for aiming it. (Shade, and what it
    # really gets, are the engine's, once it is set down and run.)
    sun = []
    for sp in compiled.get('solar_panels') or []:
        if compiled.get('sun') and owner({'name': sp['part']}) == name:
            n, to = mw._unit(sp['normal']), mw._sun_toward(compiled['sun'])
            c = max(-1.0, min(1.0, sum(n[i] * to[i] for i in range(3))))
            sun.append({'panel': sp['name'], 'off_sun_deg': round(math.degrees(math.acos(c)), 1),
                        'sunlight_w': round(max(0.0, c) * compiled['sun']['irradiance_w_m2'] * sp['area_m2'], 1)})
    keys = ('name', 'shape', 'material', 'size_m', 'at_m', 'turn_deg', 'fixed')
    return {'name': name, 'cost': checked[index]['cost'], 'problems': problems[:4], 'fits': not problems, 'sun': sun,
            'energy': pieces_energy(compiled).get(name),
            'parts': [dict({k: p[k] for k in keys if k in p},
                           **({'parts': p['parts']} if p['shape'] == 'compound' else {})) for p in mine]}


def compose(level, placements, leave_out_goal=False):
    """The level's machine with the player's pieces in it, and the goal as a
    station. Raises LevelRefused (the tray) or mw.MachineRefused (the
    machine: overlaps, nothing in the ground, ...). A goal about a piece
    not placed yet is refused -- or with leave_out_goal, left out, and what
    it needs said in spec['_needs'], so the level can still be shown."""
    spec, checked, cost, compiled = _assemble(level, placements)
    goal = level['goal']['station']['done_when']
    rule = next(iter(goal.values()))
    wanted = rule.get('part') if isinstance(rule, dict) else rule
    names = {p['name'] for p in compiled['parts']}
    clashes = clashes_of(compiled)
    if clashes:
        raise LevelRefused(clashes[:4])
    spec['stations'] = []
    if isinstance(wanted, str) and wanted not in names:
        needs = level['goal'].get('needs', f'the goal is about {wanted}, which is not here yet')
        if not leave_out_goal:
            raise LevelRefused([needs])
        spec['_needs'] = needs
    else:
        spec['stations'] = [dict(level['goal']['station'], title=level['goal']['title'],
                                 focus=level['goal'].get('focus', []))]
    # The steps on the way, after the goal: shown on the page as the chain's
    # stations, and what the engine's search steers by. One about a part
    # that is not placed yet is left out.
    joints = {j['name'] for j in compiled['joints']}
    circuits = {c['name'] for c in compiled['circuits']}
    for m in level.get('milestones', []):
        if all(x in names or x in joints or x in circuits for x in _named(m['done_when'])):
            spec['stations'].append({'title': m['title'], 'done_when': m['done_when'], 'focus': m.get('focus', [])})
    return spec, checked, cost


def _named(rule):
    """The parts, joints and circuits a station rule names."""
    out = []
    for value in rule.values():
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            out += [v for v in value if isinstance(v, str)]
        elif isinstance(value, dict):
            out += [value[k] for k in ('part', 'joint', 'photocell') if isinstance(value.get(k), str)]
    return out


# ---- energy: what a win took ---------------------------------------------------
#
# The less energy a win takes, the better. Two kinds count, both real:
#   making your pieces -- each part's mass (the engine's own densities) times
#     its material's embodied energy, typical cradle-to-gate values (ICE, the
#     Inventory of Carbon and Energy, University of Bath); ice is the heat
#     taken out to freeze it;
#   the run -- what the engine measured going in: heaters' heat (fireboxes,
#     primers), chemical energy released (powder burning), and energy drawn
#     from batteries (lasers, motors, coils; what the sun put in is free).
EMBODIED_J_PER_KG = {'oak': 10.4e6, 'iron': 25.0e6, 'aluminum': 155.0e6, 'glass': 15.0e6, 'concrete': 0.95e6,
                     'rubber': 67.5e6, 'ceramic': 40.0e6, 'ice': 0.4e6}
DENSITY = {'iron': 7870.0, 'aluminum': 2700.0, 'glass': 2500.0, 'ceramic': 3900.0, 'oak': 700.0, 'rubber': 1100.0,
           'ice': 917.0, 'concrete': 2400.0}


def _volume(part):
    if part['shape'] == 'sphere':
        return math.pi / 6.0 * part['size_m'][0] ** 3
    if part['shape'] == 'compound':
        return sum(math.pi / 4.0 * s['size_m'][0] ** 2 * s['size_m'][1] if s['shape'] == 'cylinder'
                   else math.prod(s['size_m']) for s in part['parts'])
    return math.prod(part['size_m'])


def pieces_energy(compiled):
    """{'your plank 1': {'kg': ..., 'j': ...}}: what each of the player's
    pieces weighs and took to make."""
    out = {}
    for p in compiled['parts']:
        name = owner(p)
        if name is None:
            continue
        kg = _volume(p) * DENSITY.get(p['material'], 1000.0)
        row = out.setdefault(name, {'kg': 0.0, 'j': 0.0})
        row['kg'] += kg
        row['j'] += kg * EMBODIED_J_PER_KG.get(p['material'], 20.0e6)
    return {k: {'kg': round(v['kg'], 3), 'j': round(v['j'])} for k, v in out.items()}


PROPELLANT_J_PER_KG = 2.8e6    # the engine's stand-in for gunpowder (machine_world _kit_cannon)


def run_energy(compiled, readouts):
    """What the run put in so far: heaters' heat and batteries' energy as the
    engine measured them, and the powder in the machine's charges (all of it:
    a charge is there to be fired)."""
    ledger = (readouts or {}).get('heat_ledger') or {}
    start = {b['name']: b.get('charge_j', b['capacity_j']) for b in compiled.get('batteries') or []}
    now = {b['name']: b.get('charge_j') for b in ((readouts or {}).get('machines') or {}).get('batteries') or []}
    drawn = sum(max(0.0, start[n] - now[n]) for n in start if now.get(n) is not None)
    heat = max(0.0, ledger.get('heater_in_j') or 0.0)
    parts = {p['name']: p for p in compiled['parts']}
    powder = 0.0
    for row in ((compiled.get('thermo') or {}).get('contents') or []):
        body = parts.get(row.get('body'))
        share = (row.get('contents') or {}).get('propellant', 0.0)
        if body and share:
            powder += _volume(body) * DENSITY.get(body['material'], 1000.0) * share * PROPELLANT_J_PER_KG
    return {'heat_j': round(heat), 'powder_j': round(powder), 'electric_j': round(drawn),
            'j': round(heat + powder + drawn)}


def energy_of(compiled, readouts):
    """The whole of it: the pieces' making and the run's energy, itemised."""
    pieces = pieces_energy(compiled)
    run = run_energy(compiled, readouts)
    made = sum(v['j'] for v in pieces.values())
    return {'j': made + run['j'], 'pieces_j': made, 'pieces': pieces, 'run': run}


def measure_energy(level, placements, exe, logs):
    """A rehearsal to the goal: when it happened and what the win took (a
    level's par is its own solution's)."""
    spec, _, _ = compose(level, placements)
    compiled = mw.compile_spec(spec)
    r = mw.rehearse(compiled, exe, logs, seconds=level['time_s'] + 0.3, wall_limit_s=120)
    row = (r['stations'] or [{}])[0]
    return dict(energy_of(compiled, r.get('readouts')), goal_at_s=row.get('at_s') if row.get('done') else None)


def stars(level, checked, cost, goal_at_s, helped=False, energy_j=None):
    """What a run earned, from what the engine measured: one star for the
    goal in time, a second for winning on no more than a quarter more energy
    than the level's par, a third for no more than par."""
    par = level.get('par_energy_j')
    got = {'goal': goal_at_s is not None and goal_at_s <= level['time_s']}
    if par and energy_j is not None:
        got['near_par'] = energy_j <= 1.25 * par
        got['par'] = energy_j <= par
    else:   # no energy measured: the cost and the variety of pieces, as before
        got['budget'] = cost <= level['par']
        got['style'] = len({p['piece'] for p in checked}) >= level.get('style_pieces', 1)
    count = sum(got.values()) if got['goal'] else 0
    if helped:
        # The chat placed the pieces: the goal still counts, the rest less so.
        count = min(count, 1)
    return {'stars': count, 'earned': got, 'cost': cost, 'par': level['par'], 'goal_at_s': goal_at_s,
            'helped': helped, 'energy_j': energy_j, 'par_energy_j': par}


def nudged(compiled, seed, metres=0.0015):
    """The same machine with every loose part moved by up to `metres` in each
    direction: the run-to-run wobble a real machine has."""
    rng = random.Random(seed)
    out = copy.deepcopy(compiled)
    for p in out['parts']:
        if not p['fixed']:
            p['at_m'] = [v + rng.uniform(-metres, metres) for v in p['at_m']]
    return out


def trial(level, placements, exe, logs, runs=3):
    """Run the machine `runs` times, nudged, and say in how many the goal
    happened in time. Unpaced: as fast as the engine goes."""
    spec, checked, cost = compose(level, placements)
    compiled = mw.compile_spec(spec)
    results = []
    for seed in range(runs):
        r = mw.rehearse(nudged(compiled, seed + 1) if seed else compiled, exe, logs,
                        seconds=level['time_s'] + 0.5, wall_limit_s=120)
        row = r['stations'][0] if r['stations'] else {}
        at = row.get('at_s') if row.get('done') else None
        results.append({'goal_at_s': at, 'error': r.get('error'),
                        'closest': (r.get('closest_approach') or [None])[0]})
    worked = sum(1 for x in results if x['goal_at_s'] is not None and x['goal_at_s'] <= level['time_s'])
    return {'runs': runs, 'worked': worked, 'results': results, 'cost': cost}


def preview(level, placements, exe, logs, wall_limit_s=30.0):
    """Where things will go when the level runs, as the engine works it out:
    the machine rehearsed once, unpaced, with every loose body's path, every
    hit one of them takes part in, and when the goal happens -- running on
    half a second after it, to show where things come to rest. The page draws
    it as a see-through path before anything is run. Paths of bodies that
    hardly move (under 2 cm) are left out."""
    spec, checked, cost = compose(level, placements)
    compiled = mw.compile_spec(spec)
    goal = level['goal']['station']['done_when']
    rule = next(iter(goal.values()))
    wanted = rule.get('part') if isinstance(rule, dict) else rule
    loose = [p['name'] for p in compiled['parts'] if not p['fixed']]
    track = ([wanted] if wanted in loose else []) + [n for n in loose if n != wanted][:7]
    r = mw.rehearse(compiled, exe, logs, seconds=level['time_s'] + 0.3, wall_limit_s=wall_limit_s,
                    track=track, after_s=0.5)
    row = (r['stations'] or [{}])[0]
    goal_at = row.get('at_s') if row.get('done') and row.get('at_s') is not None and row['at_s'] <= level['time_s'] else None
    paths = []
    for name in track:
        path = r.get('paths', {}).get(name) or {}
        points = path.get('points') or []
        if len(points) < 2 or math.dist(points[0][1:4], points[-1][1:4]) < 0.02 and \
                max(math.dist(points[0][1:4], p[1:4]) for p in points) < 0.02:
            continue
        paths.append({'name': name, 'goal': name == wanted, 'points': points, 'turn_wxyz': path.get('turn_wxyz')})
    # One hit per pair a quarter second apart: a contact reports itself every
    # step it lasts, a bounce a few times.
    hits, last = [], {}
    for h in r.get('hits', []):
        key = (h['body'], h['other'])
        if any(p['name'] == h['body'] for p in paths) and h['t'] - last.get(key, -1.0) >= 0.25:
            hits.append(h)
        last[key] = h['t']
    return {'paths': paths, 'hits': hits, 'goal_at_s': goal_at, 'world_time_s': r['world_time_s'],
            'wall_s': r['wall_s'], 'error': r['error'], 'zone': rule if 'at_m' in (rule if isinstance(rule, dict) else {}) else None}


def miss_m(level, rehearsal):
    """How far from the goal a rehearsal ended up: 0 when the goal happened
    in time, otherwise how near the goal zone the part came (or 1 m when the
    goal is not a zone)."""
    rows = rehearsal.get('stations') or [{}]
    row = rows[0]
    if row.get('done') and row.get('at_s') is not None and row['at_s'] <= level['time_s']:
        return 0.0
    # A chain: one metre for every step on the way not reached, and for the
    # first of them, how near its two parts came (a "hits" step) -- so a
    # ball that misses the lever by 5 cm is nearer than one that misses by
    # 50, though neither tipped it.
    titles = [m['title'] for m in level.get('milestones', [])]
    missed = [r.get('title') for r in rows[1:] if r.get('title') in titles and not r.get('done')]
    if missed:
        close = {c['station']: c['centres_m'] for c in rehearsal.get('closest_approach') or []}
        return len(missed) + min(1.0, close.get(missed[0], 1.0)) + 0.001
    near = rehearsal.get('zone_nearest_m') or {}
    return near.get(level['goal']['title'], 1.0) + 0.001


def refine(level, placements, rehearse, budget=24, scatter=0, seed=1):
    """Starting from `placements`, move one knob at a time and keep a move
    when the engine says the goal came nearer -- a plain coordinate search,
    every step of it a real run. With `scatter`, that many random settings of
    the same pieces' knobs are tried first and the search starts from the
    best of them all: nearness can mislead (a ball flying past a lever comes
    near its middle from a ramp in quite the wrong place), and a few starts
    spread over the ranges get past that. Returns (placements, rehearsal,
    runs) for the best found; the goal happened when miss_m of it is 0."""
    best = [{k: v for k, v in p.items() if k != 'cost'} for p in placements]
    spec, _, _ = compose(level, best)
    best_run = rehearse(mw.compile_spec(spec))
    best_miss, runs = miss_m(level, best_run), 1
    tray = {t['piece']: t for t in level['tray']}
    knobs = [(i, key, rule) for i, p in enumerate(best) for key, rule in tray[p['piece']]['knobs'].items()
             if 'choices' not in rule and not rule.get('free')]
    rng = random.Random(seed)
    for _ in range(scatter):
        if best_miss == 0 or runs >= budget:
            break
        trial_p = copy.deepcopy(best)
        for i, key, rule in knobs:
            step = rule.get('step', 0.01)
            trial_p[i][key] = round(round(rng.uniform(rule['min'], rule['max']) / step) * step, 4)
        try:
            spec, _, _ = compose(level, trial_p)
            compiled = mw.compile_spec(spec)
        except (LevelRefused, mw.MachineRefused):
            continue
        run = rehearse(compiled)
        runs += 1
        miss = miss_m(level, run)
        if miss < best_miss:
            best, best_run, best_miss = trial_p, run, miss
    for fraction in (0.12, 0.05, 0.02):
        improved = True
        while improved and best_miss > 0 and runs < budget:
            improved = False
            for i, key, rule in knobs:
                for sign in (1, -1):
                    if best_miss == 0 or runs >= budget:
                        break
                    trial_p = copy.deepcopy(best)
                    step = sign * fraction * (rule['max'] - rule['min'])
                    trial_p[i][key] = round(min(rule['max'], max(rule['min'], trial_p[i][key] + step)), 4)
                    if trial_p[i][key] == best[i][key]:
                        continue
                    try:
                        spec, _, _ = compose(level, trial_p)
                        compiled = mw.compile_spec(spec)
                    except (LevelRefused, mw.MachineRefused):
                        continue
                    run = rehearse(compiled)
                    runs += 1
                    miss = miss_m(level, run)
                    if miss < best_miss - 1e-4:
                        best, best_run, best_miss, improved = trial_p, run, miss, True
                        # Going the right way: keep going while it helps.
                        while best_miss > 0 and runs < budget:
                            ahead = copy.deepcopy(best)
                            ahead[i][key] = round(min(rule['max'], max(rule['min'], ahead[i][key] + step)), 4)
                            if ahead[i][key] == best[i][key]:
                                break
                            try:
                                spec, _, _ = compose(level, ahead)
                                compiled = mw.compile_spec(spec)
                            except (LevelRefused, mw.MachineRefused):
                                break
                            run = rehearse(compiled)
                            runs += 1
                            miss = miss_m(level, run)
                            if miss >= best_miss - 1e-4:
                                break
                            best, best_run, best_miss = ahead, run, miss
                        break
        if best_miss == 0:
            break
    return best, best_run, runs


def public(level):
    """What the page needs to show a level: never its solution."""
    return {k: level[k] for k in ('id', 'title', 'brief', 'teaches', 'time_s', 'budget', 'par', 'style_pieces',
                                  'tray', 'goal', 'hints', 'par_energy_j') if k in level}
