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

Levels live in client/voxel-lab/levels.json. So does the free build: a
table with no goal and every piece, as many as you like, where a player
builds whatever they want and runs it.
"""
import copy
import hashlib
import json
import math
import random
import re
import threading
from collections import OrderedDict
from pathlib import Path

import machine_world as mw
import sandbox_mechanics
import sandbox_electrics
import sandbox_water_launch
import sandbox_combinations
import sandbox_variants

SANDBOX_MODULES = (sandbox_mechanics, sandbox_electrics, sandbox_water_launch, sandbox_combinations)
EASY_ORDER = ['easy-cut', 'easy-mirror', 'easy-lens', 'easy-solar', 'easy-tackle', 'easy-water-wheel',
              'easy-spring', 'easy-gears', 'easy-weight', 'easy-motor', 'easy-power', 'easy-switch',
              'easy-bulb', 'easy-loop', 'easy-water-receiver', 'easy-heat', 'easy-catapult',
              'easy-marble-light', 'easy-water-gate', 'easy-charge-lift', 'easy-river-lift']

# Menu metadata: high-level actions the player takes, not a difficulty rating
# or the number of automatic events in the machine. Placing and adjusting one
# piece is one task; a separate cable, field operation or drum connection adds
# another. This metadata never participates in simulation or scoring.
PLAYER_TASK_COUNTS = {
    'gap': 1, 'cut': 1, 'fire': 4, 'steam': 1, 'chain': 1,
    'laser': 2, 'sun': 2, 'tackle': 1,
    'easy-cut': 1, 'easy-mirror': 1, 'easy-lens': 1, 'easy-solar': 2,
    'easy-tackle': 1, 'easy-water-wheel': 1, 'easy-spring': 1,
    'easy-gears': 1, 'easy-weight': 1, 'easy-motor': 1, 'easy-power': 1,
    'easy-switch': 2, 'easy-bulb': 1, 'easy-loop': 1,
    'easy-water-receiver': 1, 'easy-heat': 1, 'easy-catapult': 1,
    'easy-marble-light': 1, 'easy-water-gate': 2, 'easy-charge-lift': 1,
    'easy-river-lift': 2,
}

ROOT = Path(__file__).resolve().parents[1]
LEVELS_PATH = ROOT / 'client/voxel-lab/levels.json'
_variants = OrderedDict()
_variant_requests = OrderedDict()
_variant_lock = threading.RLock()


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


def _with_free_knobs(level):
    for t in level['tray']:
        # A piece whose own knob already turns it about the vertical (a
        # mirror's angle_deg) keeps that one as its turn. One that is only
        # ever turned about the vertical (a track: tipped, its slope is its
        # drop's) names the turns it has.
        own_turn = any(r.get('turning') for r in t['knobs'].values())
        for key, rule in FREE_KNOBS.items():
            if key == 'z_m' and t.get('across') is False:
                continue
            if rule.get('turning') and (not level.get('turning', True) or t.get('turning') is False
                                        or (key == 'yaw_deg' and own_turn)
                                        or ('turns' in t and key not in t['turns'])):
                continue
            t['knobs'].setdefault(key, dict(rule))
    return level


def load_levels():
    levels = json.loads(LEVELS_PATH.read_text(encoding='utf-8'))['levels']
    menu = [level['id'] for level in levels] + EASY_ORDER
    # Learn one reflection before routing a beam through two mirrors.
    # Menu order changes no level declaration, ID, saved score or simulation.
    menu.remove('easy-mirror')
    menu.insert(menu.index('laser'), 'easy-mirror')
    order = {ident: i for i, ident in enumerate(menu)}
    for module in SANDBOX_MODULES:
        levels.extend(copy.deepcopy(getattr(module, 'EASY_LEVELS', [])))
    for level in levels:
        if level.get('difficulty') == 'easy':
            level['title'] = re.sub(r'^\d+\.\s*', '', level['title'])
    levels.sort(key=lambda level: order[level['id']])
    return [_with_free_knobs(level) for level in levels]


def free_build():
    """The free build: a level with no goal, every piece in its tray."""
    level = json.loads(LEVELS_PATH.read_text(encoding='utf-8'))['free']
    tray = {row['piece']: row for row in level['tray']}
    for module in SANDBOX_MODULES:
        for row in module.TRAY:
            tray[row['piece']] = dict(copy.deepcopy(row), sandbox_builder=True)
    level['tray'] = list(tray.values())
    link = next(row for row in level['tray'] if row['piece'] == 'link')
    link['knobs']['kind']['choices'].append('spring')
    link['knobs'].update(rest_m=dict(min=.01, max=3, default=.3, step=.01, label='spring relaxed length (m)'),
                         stiffness_n_m=dict(min=1, max=2000, default=100, step=1, label='spring stiffness (N/m)'),
                         damping_n_s_m=dict(min=0, max=50, default=1, step=.1, label='internal spring damping (N s/m)'))
    return _with_free_knobs(level)


def level_by_id(level_id):
    if level_id == 'free':
        return free_build()
    with _variant_lock:
        if level_id in _variants:
            return copy.deepcopy(_variants[level_id])
    for level in load_levels():
        if level['id'] == level_id:
            return level
    raise ValueError(f'There is no level called {level_id!s}')


def fresh_easy(family_id, seed, exe, logs, recipe_id=None):
    """Issue only a native-validated recipe; shared URLs validate exact recipes.

    Cached results belong to the actual engine binary. A server restart or an
    evicted recipe is recreated and verified by this endpoint before opening.
    Private answers and preflight diagnostics never enter the public level.
    """
    if family_id not in EASY_ORDER:
        raise ValueError('Choose an authored Easy challenge family.')
    decoded = sandbox_variants.parse(recipe_id) if recipe_id else None
    if decoded and (decoded['family'] != family_id or decoded['seed'] != seed):
        raise ValueError('Shared recipe and requested family/seed differ.')
    sandbox_variants.identity(family_id, seed)
    digest = hashlib.sha256(Path(exe).read_bytes()).hexdigest()
    key = (digest, family_id, seed, recipe_id)
    with _variant_lock:
        cached = _variant_requests.get(key)
        if cached in _variants:
            _variant_requests.move_to_end(key)
            _variants.move_to_end(cached)
            return copy.deepcopy(_variants[cached])
    family = next(level for level in load_levels() if level['id'] == family_id)
    if decoded:
        level = sandbox_variants.reconstruct(family, seed, decoded['attempt'], version=decoded['version'])
        receipt = sandbox_variants.validate(level, exe, logs)
        if not receipt['valid']:
            raise ValueError('This shared challenge no longer passes its physics checks.')
        energy = receipt['mean_energy_j']
        quantum = 10 ** (math.floor(math.log10(max(energy, 1e-12))) - 2)
        level['par_energy_j'] = math.ceil(energy / quantum) * quantum
        level['variant'].update(validated=True, validation=receipt, measured_energy_j=energy)
    else:
        level = sandbox_variants.preflight(family, seed, exe, logs)
    with _variant_lock:
        _variants[level['id']] = copy.deepcopy(level)
        _variant_requests[key] = level['id']
        while len(_variants) > 512:
            _variants.popitem(last=False)
        while len(_variant_requests) > 1024:
            _variant_requests.popitem(last=False)
    return level


def requested_level(data):
    """Sandbox declarations use the same tray, ghost, preview and live engine.

    A base belongs only to a free design; it cannot replace a puzzle. Names
    beginning 'your ' are reserved for the placement overlay, so a saved
    declaration never masquerades as a tray piece or duplicates one.
    """
    level = level_by_id(data.get('level'))
    base = data.get('base')
    if base is not None:
        if not level.get('free'):
            raise ValueError('A custom machine belongs in the Sandbox, not a level')
        compiled = mw.compile_spec(base)
        if any(p['name'].startswith('your ') for p in compiled['parts']):
            raise ValueError('Names starting with "your " are reserved for tray pieces')
        level['machine'] = copy.deepcopy(base)
        level['custom_base'] = True
        sockets = [d for d in (base.get('electrical') or {}).get('devices',[]) if d.get('kind')=='socket']
        if len(sockets)==1 and set(sockets[0].get('terminal_parts',{}))=={'plus','minus'}:
            holder = sockets[0]
            row = next(t for t in level['tray'] if t['piece']=='battery')
            row['contact_holder'] = {'name':holder['name'],'terminal_parts':copy.deepcopy(holder['terminal_parts'])}
            row['knobs']['mount'].update(default='contact pack',choices=['contact pack'])
            row['knobs']['x_m']['default'] = sum(p[0] for p in holder['terminals'].values())/2
            row['knobs']['z_m']['default'] = sum(p[2] for p in holder['terminals'].values())/2
        if (base.get('ground') or {}).get('discharge_m3_s',0)>0:
            wheel=next((t for t in level['tray'] if t['piece']=='water_wheel'),None)
            if wheel:
                wheel['knobs']['radius_m']['default']=.65
                wheel['knobs']['side']['default']='off'
    return level


def sandbox_templates():
    """Starting designs, copied by the browser; the originals stay unchanged."""
    templates = [
        {'name': 'Gate and split', 'description': 'Release three marbles through a gate and flip-flop; topple six dominoes.',
         'base': None, 'placements': free_build()['example']},
        {'name': 'Chain reaction', 'description': 'Water wheel, ramp, dominoes, lever, burning rope and glass. Includes engine readings.',
         'base': json.loads((ROOT / 'client/voxel-lab/machine-default.json').read_text(encoding='utf-8')), 'placements': []},
    ]
    for module in SANDBOX_MODULES:
        templates.extend(copy.deepcopy(module.templates() if hasattr(module, 'templates') else module.TEMPLATES))
    return templates


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


def rest_height(part, parts, gap=0.002):
    """The height of a part's middle when it is set down from above at its x
    and z until it first meets something, or the ground: exact for a ball on
    a slope or the edge of a shelf, where the tops of what is under it would
    leave it in the air."""
    reach = _reach(part)
    x, z = part['at_m'][0], part['at_m'][2]
    under = [sd for q in parts for sd in mw.solids_of(q)
             for r in [_reach(sd)] if abs(sd['at_m'][0] - x) < r[0] + reach[0] and abs(sd['at_m'][2] - z) < r[2] + reach[2]]

    def clear(y):
        probe = dict(part, at_m=[x, y, z])
        return all(mw.overlap_depth(sp, sd) <= 0.0 for sp in mw.solids_of(probe) for sd in under)
    floor = reach[1]
    y = max([floor] + [sd['at_m'][1] + _reach(sd)[1] + reach[1] for sd in under])
    step = 0.01
    while y - step > floor and clear(y - step):
        y -= step
    low = max(floor, y - step)
    if clear(low):
        return low + gap
    for _ in range(14):
        mid = 0.5 * (y + low)
        if clear(mid):
            y = mid
        else:
            low = mid
    return y + gap


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
    made = {'kits': [_turned_kit(kit, k, muzzle)]}
    if (ctx or {}).get('tray', {}).get('explicit_ignition'):
        # A real coil branch with player-drawn leads. Its pins turn with the
        # barrel; merely placing a cannon does not connect it to any battery.
        # Use the compiled barrel pose, including the kit's clearance lift
        # after a tip/roll, so its visible leads cannot remain underground.
        base = (ctx or {}).get('spec', {})
        probe = mw.compile_spec(dict(made, cell_m=base.get('cell_m', .02),
                                     ground=base.get('ground')), lenient=True)
        barrel = next(p for p in probe['parts'] if p['name']==name+' barrel')
        transform = mw.rotation(barrel['turn_deg'])
        pins = {key: [round(barrel['at_m'][i] + value, 9) for i, value in enumerate(
                    mw._mat_apply(transform, offset))]
                for key, offset in (('plus', [0, .075, -.045]), ('minus', [0, .075, .045]))}
        made['electrical'] = {'devices': [dict(name=name, kind='coil', part=name+' barrel',
            heats=name+' charge', resistance_ohm=.1, terminals=pins)]}
    return made


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
    made = {'parts': [plate, post],
            'solar_panels': [{'name': name, 'part': name, 'battery': ctx['tray'].get('battery', 'battery'),
                              'normal': [round(v, 9) for v in mw._mat_apply(m, [0.0, 1.0, 0.0])],
                              'area_m2': 0.25, 'efficiency': 0.2}]}
    if ctx['tray'].get('explicit_power'):
        # The panel collects into its own finite store until a cable chooses
        # a receiver. No energy reaches the winch through an implicit link.
        store = name + ' local battery'
        made['solar_panels'][0]['battery'] = store
        made['batteries'] = [{'name': store, 'in': post['name'], 'capacity_j': 20000,
                              'voltage_v': 12, 'charge_j': 0}]
    return made


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
    # The pulleys the rope turns over, each in an iron block hung from the
    # underside of the level's beam (its middle where the rope turns).
    block = ctx['tray'].get('pulley_m', 0.04)
    pulleys = [{'name': f'{name} pulley {i + 1}', 'shape': 'box', 'material': 'iron', 'size_m': [block] * 3,
                'at_m': [at[0], beam, at[2]], 'fixed': True}
               for i, at in enumerate(([x, beam, z], load['at_m']))]
    rope = {'name': name + ' rope', 'kind': 'pulley', 'a': name, 'b': load['name'],
            'at_m': [x, round(y + 0.5 * side, 4), z], 'at_b_m': [load['at_m'][0], round(top, 4), load['at_m'][2]],
            'over_a_m': [x, beam, z], 'over_b_m': [load['at_m'][0], beam, load['at_m'][2]], 'ratio': k['ratio']}
    return {'parts': [weight] + pulleys, 'joints': [rope]}


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


def _marble(name, k, ctx):
    """A loose marble set down at (x_m, z_m) on whatever is under it -- a
    shelf, a track, the ground. From then on gravity and contact move it."""
    d = k.get('diameter_m', 0.04)
    part = {'name': name, 'shape': 'sphere', 'material': k.get('material', 'iron'), 'size_m': [d, d, d],
            'at_m': [k['x_m'], 0.0, k.get('z_m', 0.0)], 'turn_deg': [0.0, 0.0, 0.0], 'fixed': False}
    part['at_m'][1] = round(rest_height(part, ctx['parts']), 4)
    return {'parts': [part]}


TRACK_ENDS = {'open': {}, 'stop': {'end_stop': True}, 'gate': {'barrier': True},
              'gate that stays open': {'barrier': {'stays_open': True}}}


def _track(name, k, ctx=None):
    """A chute: a board with a rail each side, its top end at (x_m,
    top_height_m), dropping drop_m over run_m toward +x until it is turned
    (about its top end). Its far end is open (what rolls down drops off), a
    stop (it stays there) or a gate (it waits there until something presses
    the gate's arm down). A shelf is a short one, tilted a little toward
    its gate."""
    top = [k['x_m'], k['top_height_m'], k.get('z_m', 0.0)]
    kit = dict({'kit': 'ramp', 'name': name, 'top_m': top,
                'bottom_m': [k['x_m'] + k['run_m'], round(k['top_height_m'] - k['drop_m'], 4), k.get('z_m', 0.0)],
                'width_m': k.get('width_m', 0.08), 'thickness_m': 0.02}, **TRACK_ENDS[k.get('end', 'open')])
    return {'kits': [_turned_kit(kit, k, top)]}


def _bend(name, k, ctx=None):
    """A curved track: its top end at (x_m, top_height_m, z_m), starting the
    way it is turned (yaw_deg), turning turn_deg (positive to the left) round
    radius_m and dropping drop_m."""
    return {'kits': [{'kit': 'bend', 'name': name, 'start_m': [k['x_m'], k['top_height_m'], k.get('z_m', 0.0)],
                      'heading_deg': k.get('yaw_deg', 0.0), 'turn_deg': k['turn_deg'], 'radius_m': k['radius_m'],
                      'drop_m': k['drop_m']}]}


def _funnel(name, k, ctx=None):
    """A funnel, its mouth's middle at (x_m, height_m, z_m): what lands on
    it rolls in and drops out of the hole in its middle."""
    return {'kits': [{'kit': 'funnel', 'name': name, 'at_m': [k['x_m'], k['height_m'], k.get('z_m', 0.0)],
                      'size_m': k['size_m'], 'depth_m': k.get('depth_m', 0.12)}]}


def _flipflop(name, k, ctx=None):
    """A flip-flop on its pin at (x_m, height_m, z_m): marbles dropped on its
    middle go one way, then the other. It starts tipped left (its -x end
    down: the first marble goes right) or right."""
    pivot = [k['x_m'], k['height_m'], k.get('z_m', 0.0)]
    return {'kits': [_turned_kit({'kit': 'flip_flop', 'name': name, 'pivot_m': pivot,
                                  'tipped': '-x' if k.get('tipped', 'left') == 'left' else '+x'}, k, pivot)]}


def _block(name, k, ctx):
    """A fixed block -- a post, a wall, a step, a stop -- set down at (x_m,
    z_m) on whatever is under it."""
    part = {'name': name, 'shape': 'box', 'material': k.get('material', 'concrete'),
            'size_m': [k['length_m'], k['tall_m'], k['depth_m']], 'at_m': [k['x_m'], 0.0, k.get('z_m', 0.0)],
            'turn_deg': mw.turn_of(mw.heading(*(_turn(k) or [0.0, 0.0, 0.0]))), 'fixed': True}
    part['at_m'][1] = round(rest_height(part, ctx['parts'], gap=0.0), 4)
    return {'parts': [part]}


def _dominoes(name, k, ctx):
    """A row of oak dominoes from (x_m, z_m) along +x until it is turned,
    standing on whatever is under the row."""
    count, spacing, tall = int(round(k['count'])), k['spacing_m'], k['tall_m']
    x, z = k['x_m'], k.get('z_m', 0.0)
    yaw = math.radians(k.get('yaw_deg', 0.0))
    end = [x + (count - 1) * spacing * math.cos(yaw), z - (count - 1) * spacing * math.sin(yaw)]
    base = set_down_height(ctx['parts'], min(x, end[0]) - 0.04, max(x, end[0]) + 0.04,
                           min(z, end[1]) - 0.04, max(z, end[1]) + 0.04)
    start = [x, round(base + 0.001, 4), z]
    return {'kits': [_turned_kit({'kit': 'domino_row', 'name': name, 'start_m': start, 'direction': '+x',
                                  'count': count, 'spacing_m': spacing, 'size_m': [0.02, tall, 0.06],
                                  'material': 'oak'}, k, start)]}


def _lever(name, k, ctx=None):
    """A seesaw: a plank on a pin on a block standing on the ground at
    (x_m, z_m), along x until it is turned."""
    pivot = [k['x_m'], k['pivot_height_m'], k.get('z_m', 0.0)]
    return {'kits': [_turned_kit({'kit': 'lever', 'name': name, 'pivot_m': pivot, 'length_m': k['length_m'],
                                  'width_m': 0.08, 'thickness_m': 0.02, 'limit_deg': k.get('limit_deg', 20),
                                  'along': 'x'}, k, pivot)]}


LINK_JOINTS = {'glue': 'fix', 'pin': 'hinge', 'string': 'tie', 'spring': 'spring'}
LINK_AXES = {'along x': [1.0, 0.0, 0.0], 'along z': [0.0, 0.0, 1.0], 'upright': [0.0, 1.0, 0.0]}


def _link(name, k, ctx=None):
    """Two parts joined where the player picked them: glued together there,
    on a pin there (turning about along x, along z or upright), or tied by a
    string from the point picked on one to the point picked on the other, as
    long as it was then. Nothing about what the joint does is decided here."""
    a, b, at = k['a'], k['b'], k['at_m']
    joint = {'name': name, 'kind': LINK_JOINTS[k['kind']], 'a': a, 'b': b, 'at_m': list(at)}
    if k['kind'] == 'pin':
        joint.update(axis=LINK_AXES[k.get('axis', 'along z')], friction_n_m=0.002)
    elif k['kind'] == 'glue':
        joint.update(axis=[0.0, 1.0, 0.0])
    elif k['kind'] == 'spring':
        joint.update(at_b_m=list(k['at_b_m']), rest_m=k['rest_m'], stiffness_n_m=k['stiffness_n_m'], damping_n_s_m=k['damping_n_s_m'])
    else:
        joint.update(at_b_m=list(k['at_b_m']), length_m=round(math.dist(at, k['at_b_m']), 5))
    return {'joints': [joint]}


PIECES = {'plank': _plank, 'knife': _knife, 'cannon': _cannon, 'steam': _steam, 'ramp': _ramp, 'mirror': _mirror,
          'solar': _solar, 'tackle': _tackle, 'lens': _lens, 'marble': _marble, 'track': _track, 'shelf': _track,
          'flipflop': _flipflop, 'block': _block, 'dominoes': _dominoes, 'lever': _lever, 'link': _link,
          'bend': _bend, 'funnel': _funnel}


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
            if any(rule.get(ref) for ref in ('part', 'hinge', 'terminal', 'power_port')):
                # A link's ends: a part of the machine, named.
                if not isinstance(value, str) or not 0 <= len(value) <= 120:
                    problems.append(f'{what}: {key} names an existing connection')
                knobs[key] = value
                continue
            if rule.get('point'):
                if value is None and not rule.get('needed', True):
                    continue
                if (not isinstance(value, list) or len(value) != 3 or
                        not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 20
                                for v in value)):
                    problems.append(f'{what}: {key} is a point, three numbers in metres')
                    continue
                knobs[key] = [float(v) for v in value]
                continue
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
        if t['piece'] == 'link' and knobs.get('a') == knobs.get('b'):
            problems.append(f'{what}: a link joins two different parts')
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


class _Context(dict):
    """What a piece is built among: its tray row, and -- worked out only for
    a piece that is set down on what is there -- the parts already there."""

    def __init__(self, spec, lenient, tray):
        super().__init__(tray=tray, spec=spec)
        self._spec, self._lenient = spec, lenient

    def __missing__(self, key):
        if key != 'parts':
            raise KeyError(key)
        # Other subsystems may still have future endpoint references while
        # declarations are staged. Final compilation below remains strict.
        self['parts'] = mw.compile_spec(dict(self._spec, stations=[]), lenient=True)['parts']
        return self['parts']


def merge_fragment(spec, fragment, nested=False):
    """Append declaration arrays and merge nested subsystems without losing a device."""
    for key, value in fragment.items():
        if key == 'mirrors' and not nested:
            spec.setdefault('light', {}).setdefault('mirrors', []).extend(copy.deepcopy(value))
        elif isinstance(value, list):
            spec[key] = list(spec.get(key) or []) + copy.deepcopy(value)
        elif isinstance(value, dict):
            merge_fragment(spec.setdefault(key, {}), value, nested=True)
        elif key not in spec or spec[key] == value:
            spec[key] = copy.deepcopy(value)
        else:
            raise ValueError(f'Conflicting declaration setting: {key}')


def _assemble(level, placements, lenient=False):
    """The level's machine with the player's pieces built into it, and that
    machine compiled. lenient: as far as it can be, with its problems in it
    (mw.compile_spec), and the budget left unchecked."""
    checked, cost = check_placements(level, placements, budget=not lenient)
    spec = copy.deepcopy(level['machine'])
    spec.setdefault('kits', [])
    spec.setdefault('parts', [])
    spec['title'] = level['title']
    # Nothing floats: the level's own stands first, so a piece is set down
    # on them as on anything else.
    spec['parts'] += _level_held_up(level, spec, lenient)
    tray = {t['piece']: t for t in level['tray']}
    pending = list(enumerate(checked))
    complete = set()
    ordered = []
    while pending:
        ready = None
        for pos, (i, p) in enumerate(pending):
            refs = [p.get(key, '') for key, rule in tray[p['piece']]['knobs'].items()
                    if any(rule.get(ref) for ref in ('part', 'hinge', 'terminal', 'power_port'))]
            dependencies = {int(match.group(1)) - 1 for ref in refs
                            for match in [re.match(r'^your \S+ (\d+)(?:\b|:)', ref)] if match and int(match.group(1)) - 1 != i}
            if dependencies <= complete:
                ready = pos
                break
        if ready is None:
            raise LevelRefused(['Connections contain a cycle or name a tray piece that is not present'])
        i, p = pending.pop(ready)
        ordered.append((i, p))
        complete.add(i)
    for i, p in ordered:
        knobs = {k: v for k, v in p.items() if k not in ('piece', 'cost')}
        # What is there already, for a piece that is set down on it, and
        # what the tray says about it (the battery a panel is wired to).
        ctx = _Context(spec, lenient, tray[p['piece']])
        builders = PIECES
        if level.get('free') or tray[p['piece']].get('sandbox_builder'):
            builders = dict(PIECES)
            for module in SANDBOX_MODULES:
                builders.update(module.PIECES)
        made = builders[p['piece']](f'your {p["piece"]} {i + 1}', knobs, ctx)
        merge_fragment(spec, made)
    compiled = mw.compile_spec(dict(spec, stations=[]), lenient=lenient)
    # And the player's pieces: a mirror stands on a post, not in the air.
    stands = hold_up(compiled['parts'], spec.get('cell_m', 0.02), only_player=level.get('custom_base', False))
    if stands:
        spec['parts'] += stands
        compiled = mw.compile_spec(dict(spec, stations=[]), lenient=lenient)
    return spec, checked, cost, compiled


# ---- nothing floats ----------------------------------------------------------
#
# Everything in the world is held up: a fixed part stands on the ground, or is
# bolted to a fixed part that is held up, by a chain of them down to the
# ground. One that would hang in the air (a mirror, a laser, a cannon's
# barrel, a ramp at a height) gets a stand: a concrete post from the top of
# whatever is under it up to its underside -- two under a long part. A
# player's stand is part of the piece (named for it), so it counts in the
# piece's energy and may not go into anything. Loose parts need none: gravity
# and contact hold them, or they fall.

TOUCH_M = 0.004      # parts this close are touching (bolted together)
STAND_SIDE_M = 0.04


def _reach(solid):
    """A solid's half extents along x, y and z in the world."""
    if solid['shape'] == 'sphere':
        return [0.5 * solid['size_m'][0]] * 3
    axes, half = mw._axes(solid), mw._half(solid)
    return [sum(abs(axes[j][i]) * half[j] for j in range(3)) for i in range(3)]


def _gap(a, b):
    """How far apart two solids are (negative: they overlap), by the widest
    separating axis -- not the first one found, which can say less."""
    if a['shape'] == 'sphere' or b['shape'] == 'sphere':
        return -mw.overlap_depth(a, b)
    ca, cb, aa, ab, ha, hb = a['at_m'], b['at_m'], mw._axes(a), mw._axes(b), mw._half(a), mw._half(b)
    d = [cb[i] - ca[i] for i in range(3)]
    axes = aa + ab
    for u in aa:
        for v in ab:
            c = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            n = math.sqrt(sum(x * x for x in c))
            if n > 1e-9:
                axes.append([x / n for x in c])
    return max(abs(sum(d[k] * ax[k] for k in range(3)))
               - sum(ha[j] * abs(sum(aa[j][k] * ax[k] for k in range(3))) for j in range(3))
               - sum(hb[j] * abs(sum(ab[j][k] * ax[k] for k in range(3))) for j in range(3)) for ax in axes)


def held_up(parts):
    """The names of the fixed parts that are held up: on the ground, or
    touching one that is, by a chain of them."""
    fixed = [p for p in parts if p.get('fixed')]
    solids = {p['name']: [(s, s['at_m'], _reach(s)) for s in mw.solids_of(p)] for p in fixed}
    held = {p['name'] for p in fixed if min(c[1] - r[1] for _, c, r in solids[p['name']]) <= TOUCH_M}
    todo = list(held)

    def near(x, y):
        return any(all(abs(cx[i] - cy[i]) <= rx[i] + ry[i] + TOUCH_M for i in range(3))
                   and _gap(sx, sy) <= TOUCH_M for sx, cx, rx in solids[x] for sy, cy, ry in solids[y])
    while todo:
        name = todo.pop()
        for p in fixed:
            if p['name'] not in held and near(name, p['name']):
                held.add(p['name'])
                todo.append(p['name'])
    return held


def _underside(solid, x, z):
    """How high a vertical line at (x, z) first meets a solid, coming up from
    below; None if it misses."""
    c = solid['at_m']
    if solid['shape'] == 'sphere':
        r = 0.5 * solid['size_m'][0]
        q = r * r - (x - c[0]) ** 2 - (z - c[2]) ** 2
        return c[1] - math.sqrt(q) if q >= 0 else None
    lo, hi = -math.inf, math.inf
    for a, h in zip(mw._axes(solid), mw._half(solid)):
        k = (x - c[0]) * a[0] + (z - c[2]) * a[2]
        if abs(a[1]) < 1e-9:
            if abs(k) > h:
                return None
            continue
        y0, y1 = sorted(((-h - k) / a[1], (h - k) / a[1]))
        lo, hi = max(lo, c[1] + y0), min(hi, c[1] + y1)
    return lo if lo <= hi else None


def _stand_at(part, solids, parts, x, z, cell, name):
    """A post at (x, z) from the top of the highest fixed thing under it up to
    where it meets the part's underside; None where it would miss the part
    or the part is as good as resting there already."""
    if all(_underside(sd, x, z) is None for sd in solids):
        return None
    w = 0.5 * STAND_SIDE_M
    # Its top meets the part and goes into none of it.
    top = min(u for dx, dz in ((0, 0), (-w, -w), (-w, w), (w, -w), (w, w)) for sd in solids
              for u in [_underside(sd, x + dx, z + dz)] if u is not None)
    base = 0.0
    for q in parts:
        if not q.get('fixed') or q['name'] == part['name']:
            continue
        for sd in mw.solids_of(q):
            cq, r = sd['at_m'], _reach(sd)
            if abs(cq[0] - x) < r[0] + w and abs(cq[2] - z) < r[2] + w and cq[1] + r[1] <= top + 1e-6:
                base = max(base, cq[1] + r[1])
    if top - base <= TOUCH_M:
        return None
    # The engine builds it of whole cells: the next whole number up, so it
    # reaches into what it holds (by less than a cell) rather than stopping
    # short of it.
    height = round(math.ceil((top - base) / cell - 1e-6) * cell, 6)
    return {'name': name, 'shape': 'box', 'material': 'concrete', 'size_m': [STAND_SIDE_M, height, STAND_SIDE_M],
            'at_m': [round(x, 4), base + 0.5 * height, round(z, 4)], 'turn_deg': [0.0, 0.0, 0.0], 'fixed': True}


def _clear(stand, part, parts):
    """Whether a stand goes into nothing but what it holds (and the rest of
    its own piece): a lever, a table's edge, a ball are in its way."""
    mine = owner(part)
    for q in parts:
        if q['name'] == part['name'] or (mine is not None and owner(q) == mine):
            continue
        if any(mw.overlap_depth(stand, sd) > 0.001 for sd in mw.solids_of(q)):
            return False
    return True


def _stands_for(part, parts, cell=0.02):
    """Posts holding `part` up: under its middle, or under both ends of a long
    part (along its longest level direction). Each goes where it is clear,
    tried a little further along the part at a time, as a table's leg is
    moved off a pipe; one that finds nowhere clear is left out while another
    holds the part. When none finds anywhere, they stand where they would,
    and what they go into says why the part cannot go there."""
    solids = mw.solids_of(part)
    big = max(solids, key=lambda sd: math.prod(sd['size_m']))
    axes, half = mw._axes(big), mw._half(big)
    j = max(range(3), key=lambda j: 2 * half[j] * math.hypot(axes[j][0], axes[j][2]))
    length = 2 * half[j] * math.hypot(axes[j][0], axes[j][2])
    across = math.hypot(axes[j][0], axes[j][2])
    u = [axes[j][0] / across, axes[j][2] / across] if across > 1e-9 else [1.0, 0.0]
    c = big['at_m']
    if length > 0.6:
        groups = [[side * f for f in (0.3, 0.2, 0.4, 0.1, 0.45)] for side in (-1, 1)]
    else:
        groups = [[0.0, 0.15, -0.15, 0.3, -0.3]]
    chosen, nominal = [], []
    for n, fractions in enumerate(groups):
        name = part['name'] + ' stand' + (f' {n + 1}' if len(groups) > 1 else '')
        tries = [st for f in fractions
                 for st in [_stand_at(part, solids, parts, c[0] + f * length * u[0], c[2] + f * length * u[1], cell, name)]
                 if st is not None]
        if tries:
            nominal.append(tries[0])
            clear = next((st for st in tries if _clear(st, part, parts)), None)
            if clear is not None:
                chosen.append(clear)
    return chosen or nominal


def hold_up(parts, cell=0.02, only_player=False):
    """The stands that keep every fixed part in `parts` from floating."""
    parts, stands, tried = list(parts), [], set()
    names = {p['name'] for p in parts}
    while True:
        held = held_up(parts)
        floating = [p for p in parts if p.get('fixed') and p['name'] not in held and p['name'] not in tried
                    and (not only_player or owner(p) is not None)]
        if not floating:
            return stands
        # The biggest first: what is bolted to it is held up once it is.
        p = max(floating, key=_volume)
        tried.add(p['name'])
        more = [st for st in _stands_for(p, parts, cell) if st['name'] not in names]
        names |= {st['name'] for st in more}
        stands += more
        parts += more


_level_stands = {}


def _level_held_up(level, spec, lenient):
    """The level's own stands, once a level (its machine never changes)."""
    if level.get('custom_base'):
        # Preserve the declaration's explicit anchors and kit supports. The
        # tray overlay still gets stands; rewriting the base could put a
        # spout's new stand through its water wheel and change its physics.
        return []
    key = (level['id'], json.dumps(level['machine'], sort_keys=True))
    if key not in _level_stands:
        _level_stands[key] = hold_up(mw.compile_spec(dict(spec, stations=[]), lenient=lenient)['parts'],
                                     spec.get('cell_m', 0.02))
    return copy.deepcopy(_level_stands[key])


def owner(part):
    """'your plank 1' for every part a player's piece made, else None."""
    bits = part['name'].split(' ')
    return ' '.join(bits[:3]) if bits[0] == 'your' and len(bits) >= 3 else None


def clashes_of(compiled):
    """Nothing of the player's goes into anything else -- not the level, not
    another piece. (The machine itself lets two bolted parts meet; a
    player's bolted mirror stood inside a wall, and a bolted plank inside
    the tables it should have rested on.)"""
    deepest = {}
    solids = {p['name']: [(sd, _reach(sd)) for sd in mw.solids_of(p)] for p in compiled['parts']}

    def near(a, b):
        return any(all(abs(sa['at_m'][i] - sb['at_m'][i]) < ra[i] + rb[i] for i in range(3))
                   for sa, ra in solids[a['name']] for sb, rb in solids[b['name']])
    for a in compiled['parts']:
        if owner(a) is None:
            continue
        for b in compiled['parts']:
            if b is a or owner(b) == owner(a) or (owner(b) is not None and b['name'] < a['name']) or not near(a, b):
                continue
            depth = max(mw.overlap_depth(sa, sb) for sa in mw.solids_of(a) for sb in mw.solids_of(b))
            if depth > 0.001:
                # A piece's stand going into something is the piece going into it.
                what = a['name'][:-len(' stand')] if a['name'].endswith(' stand') else a['name']
                into = owner(b) if b['name'].startswith(f'{owner(b)} stand') else b['name']
                key = (what, into)
                deepest[key] = max(deepest.get(key, 0.0), depth)
    return [f'{what} goes {depth * 1000:.0f} mm into {into}; move it' for (what, into), depth in deepest.items()]


# ---- snap points ---------------------------------------------------------------
#
# Where one piece hands a marble on to the next: a track's far end (out) and
# top end (in), a flip-flop's middle (in) and its two ends (out), a gate's
# paddle (a trigger: something dropped on it opens the gate). A piece moved
# near one of another piece's ports is put where the two connect: a track's
# top end just under and past another's far end, a track's far end just
# above a flip-flop's middle or a gate's paddle, a flip-flop under a track's
# far end with its board behind, where the marbles fly to.

SNAP_M = 0.1          # how near (across the ground) a port has to come
SNAP_RISE_M = 1.0     # and no more than this above or below


def _forward(p):
    yaw = math.radians(p.get('yaw_deg', 0.0))
    return [math.cos(yaw), 0.0, -math.sin(yaw)]


def ports(checked, compiled):
    """Every placed piece's ports: {'piece': index, 'name', 'port', 'kind'
    ('in', 'out' or 'trigger'), 'at', 'dir' (the way a marble goes there)}."""
    out, parts = [], {p['name']: p for p in compiled['parts']}
    for i, p in enumerate(checked):
        name, fwd = f'your {p["piece"]} {i + 1}', _forward(p)

        def add(port, kind, at, way):
            out.append({'piece': i, 'name': name, 'port': port, 'kind': kind,
                        'at': [round(v, 4) for v in at], 'dir': [round(v, 4) for v in way]})
        if p['piece'] in ('track', 'shelf', 'ramp'):
            top = [p['x_m'], p['top_height_m'], p.get('z_m', 0.0)]
            low = p['top_height_m'] - p['drop_m'] if 'drop_m' in p else p['foot_height_m']
            far = [top[0] + p['run_m'] * fwd[0], low, top[2] + p['run_m'] * fwd[2]]
            if p['piece'] != 'ramp':
                add('top end', 'in', top, fwd)
            if p.get('end', 'open') != 'stop':
                add('far end', 'out', far, fwd)
            barrier = parts.get(name + ' barrier')
            if barrier:
                paddle = mw.solids_of(barrier)[3]['at_m']
                add('gate paddle', 'trigger', [paddle[0], paddle[1] + 0.005, paddle[2]], fwd)
        elif p['piece'] == 'bend':
            top = [p['x_m'], p['top_height_m'], p.get('z_m', 0.0)]
            _, end, way = mw.bend_path(top, p.get('yaw_deg', 0.0), p['turn_deg'], p['radius_m'], p['drop_m'])
            h = math.radians(way)
            add('top end', 'in', top, fwd)
            add('far end', 'out', end, [math.cos(h), 0.0, -math.sin(h)])
        elif p['piece'] == 'funnel':
            # In at its mouth, from above; out of its hole, falling straight down.
            depth = p.get('depth_m', 0.12)
            add('mouth', 'in', [p['x_m'], p['height_m'] + 0.06, p.get('z_m', 0.0)], fwd)
            add('hole', 'out', [p['x_m'], p['height_m'] - depth - 0.02, p.get('z_m', 0.0)], [0.0, 0.0, 0.0])
        elif p['piece'] == 'flipflop':
            pin = [p['x_m'], p['height_m'], p.get('z_m', 0.0)]
            # Its board is behind it (-z before it is turned): marbles come in
            # from the front, toward the board.
            yaw = math.radians(p.get('yaw_deg', 0.0))
            toward_board = [-math.sin(yaw), 0.0, -math.cos(yaw)]
            add('middle', 'in', [pin[0], pin[1] + FLIP_DROP_M, pin[2]], toward_board)
            # Its ends swing 3 cm up and down as it tips, and a marble leaves
            # one slowly: what joins there goes just beyond the end and well
            # below it -- a track's top end 14 cm out and 14 cm down, clear of
            # the rocker and its board, as in the example that works.
            for sign, label in ((1, 'right end'), (-1, 'left end')):
                add(label, 'out', [pin[0] + sign * 0.11 * fwd[0], pin[1] - 0.10, pin[2] + sign * 0.11 * fwd[2]],
                    [sign * v for v in fwd])
    return out


FLIP_DROP_M = 0.11    # a track's far end this far over a flip-flop's pin drops onto its middle
LEAD_M = 0.04         # and this far short of it, along the way it comes


def _connect(p, m, q):
    """The knobs that put port m of piece p where it connects to port q of
    another piece -- moved by the gap between m and where m should be,
    across by x_m and z_m and up by its height -- or None when the two do not
    connect."""
    rise_knob = 'height_m' if p['piece'] in ('flipflop', 'funnel') else 'top_height_m'

    def moved_by(target):
        return {'x_m': p['x_m'] + target[0] - m['at'][0], 'z_m': p.get('z_m', 0.0) + target[2] - m['at'][2],
                rise_knob: p[rise_knob] + target[1] - m['at'][1]}
    way = m['dir']
    if m['port'] == 'top end' and q['kind'] == 'out':
        # Under it and a little past it: what rolls off drops onto this.
        return moved_by([q['at'][0] + 0.03 * q['dir'][0], q['at'][1] - 0.04, q['at'][2] + 0.03 * q['dir'][2]])
    if m['port'] == 'far end' and q['kind'] in ('in', 'trigger'):
        if q['port'] == 'top end':
            return moved_by([q['at'][0] - 0.03 * way[0], q['at'][1] + 0.04, q['at'][2] - 0.03 * way[2]])
        if q['kind'] == 'trigger':
            # Short of the paddle: what rolls off flies on a little as it falls.
            return moved_by([q['at'][0] - 0.05 * way[0], q['at'][1] + 0.065, q['at'][2] - 0.05 * way[2]])
        return moved_by([q['at'][0] - LEAD_M * way[0], q['at'][1], q['at'][2] - LEAD_M * way[2]])
    if p['piece'] == 'funnel' and m['port'] == 'mouth' and q['kind'] == 'out':
        # Under what comes out there, a little past it, its mouth 8 cm lower.
        return moved_by([q['at'][0] + 0.06 * q['dir'][0], q['at'][1] - 0.02, q['at'][2] + 0.06 * q['dir'][2]])
    if p['piece'] == 'flipflop' and m['port'] == 'middle' and q['kind'] == 'out':
        way = q['dir']
        pin = [q['at'][0] + LEAD_M * way[0], q['at'][1] - FLIP_DROP_M, q['at'][2] + LEAD_M * way[2]]
        # Its board behind it, where what comes in flies to.
        return {'x_m': pin[0], 'z_m': pin[2], 'height_m': pin[1],
                'yaw_deg': round(math.degrees(math.atan2(-way[0], -way[2])))}
    return None


def _seat(p, q):
    """A marble at the top of a track: just in from its end."""
    r = 0.5 * p.get('diameter_m', 0.04)
    return {'x_m': q['at'][0] + (0.03 + r) * q['dir'][0], 'z_m': q['at'][2] + (0.03 + r) * q['dir'][2]}


def join_to(level, placed, index, to, port):
    """Piece `index` of `placed` moved to connect to port `port` of piece
    `to`, however far apart they are: the placements with it moved. Raises
    LevelRefused when there is no such port, or the two do not connect."""
    _, checked, _, compiled = _assemble(level, placed[:index + 1], lenient=True)
    found = ports(checked, compiled)
    q = next((q for q in found if q['piece'] == to and q['port'] == port), None)
    what = f'piece {index + 1}'
    if q is None:
        have = [r['port'] for r in found if r['piece'] == to]
        raise LevelRefused([f'{what}: piece {to + 1} has no port "{port}"' + (f' (it has {", ".join(have)})' if have else '')])
    p = checked[index]
    if q['kind'] == 'out' and p['piece'] in ('track', 'shelf', 'bend'):
        # It starts the way what leaves there goes: turned straight away, it
        # would run into what it joins (a turn there is a bend's to make).
        p = dict(p, yaw_deg=round(math.degrees(math.atan2(-q['dir'][2], q['dir'][0]))))
        placed = list(placed)
        placed[index] = dict(placed[index], yaw_deg=p['yaw_deg'])
        _, checked, _, compiled = _assemble(level, placed[:index + 1], lenient=True)
        found = ports(checked, compiled)
    if p['piece'] == 'marble':
        knobs = _seat(p, q) if q['port'] == 'top end' else None
        if knobs:
            # Marbles joined to the same top end line up along it, one behind
            # another, rather than one on top of the other.
            gap = p.get('diameter_m', 0.04) + 0.005
            taken = [[o['x_m'], o.get('z_m', 0.0)] for o in checked[:index] if o['piece'] == 'marble']
            for k in range(40):
                at = [knobs['x_m'] + k * gap * q['dir'][0], knobs['z_m'] + k * gap * q['dir'][2]]
                if all(math.dist(at, o) > 0.5 * gap for o in taken):
                    knobs = {'x_m': at[0], 'z_m': at[1]}
                    break
    else:
        knobs = next((k for m in found if m['piece'] == index for k in [_connect(p, m, q)] if k), None)
    if not knobs:
        raise LevelRefused([f'{what}: a {p["piece"]} does not join a {port}'])
    out = list(placed)
    out[index] = dict(placed[index], **{k: round(v, 4) for k, v in knobs.items()})
    return out


def centred(level, placed):
    """A build moved across the ground so the middle of what it covers is at
    the middle of the table: every piece's x_m and z_m, and the points its
    joins are made at, by the same amount."""
    _, _, _, compiled = _assemble(level, placed, lenient=True)
    reach = [(sd['at_m'], _reach(sd)) for p in compiled['parts'] if owner(p) for sd in mw.solids_of(p)]
    if not reach:
        return placed
    shift = [-round(0.5 * (min(c[i] - r[i] for c, r in reach) + max(c[i] + r[i] for c, r in reach)), 2) for i in (0, 2)]
    out = []
    for p in placed:
        q = dict(p)
        if 'x_m' in q:
            q['x_m'], q['z_m'] = round(q['x_m'] + shift[0], 4), round(q.get('z_m', 0.0) + shift[1], 4)
        for key in ('at_m', 'at_b_m'):
            if isinstance(q.get(key), list):
                q[key] = [round(q[key][0] + shift[0], 4), q[key][1], round(q[key][2] + shift[1], 4)]
        out.append(q)
    return out


def resting_on(compiled, point, radius):
    """The part a ball at `point` rests on (the first thing under it within 5
    mm), or 'the ground', or None when it is in the air."""
    if point[1] - radius < 0.005:
        return 'the ground'
    probe = {'name': 'probe', 'shape': 'sphere', 'size_m': [2 * radius + 0.01] * 3, 'at_m': list(point), 'turn_deg': [0, 0, 0]}
    near = [(mw.overlap_depth(probe, sd), p['name']) for p in compiled['parts'] for sd in mw.solids_of(p)
            if p['name'] != 'probe' and abs(sd['at_m'][0] - point[0]) < 2.0 and abs(sd['at_m'][2] - point[2]) < 2.0]
    touching = [n for depth, n in near if depth > 0.0]
    return touching[0] if touching else None


def snap(level, placed, index, compiled):
    """The knobs that put piece `index` where it connects to the nearest port
    of another piece, and what it connects to; None when nothing is near."""
    p = placed[index]
    theirs = [q for q in ports(placed, compiled) if q['piece'] != index]
    mine = [q for q in ports(placed, compiled) if q['piece'] == index]
    best = None

    def consider(d, knobs, to):
        nonlocal best
        if best is None or d < best[0]:
            best = (d, knobs, to)

    def near(a, b):
        return math.hypot(a[0] - b[0], a[2] - b[2]), abs(a[1] - b[1])
    for m in mine:
        for q in theirs:
            d, rise = near(m['at'], q['at'])
            knobs = _connect(p, m, q) if d <= SNAP_M and rise <= SNAP_RISE_M else None
            if knobs:
                consider(d, knobs, q)
    for q in theirs:
        if p['piece'] == 'marble' and q['port'] == 'top end':
            d, rise = near([p['x_m'], 0.0, p.get('z_m', 0.0)], q['at'])
            if d <= SNAP_M:
                consider(d, _seat(p, q), q)
    if best is None:
        return None
    _, knobs, to = best
    return {'knobs': {k: round(v, 4) for k, v in knobs.items()}, 'to': to['name'], 'port': to['port']}


def editing_guide(level, checked, index, compiled, key):
    """Editor annotations from compiled geometry, never forces or simulation.

    Compare a small permitted adjustment with the current setup. Face centres
    identify the moving edges even after turning, tipping or resting a piece.
    The comparison is discarded; it cannot modify the player's placements.
    """
    p = checked[index]
    rule = next(t for t in level['tray'] if t['piece'] == p['piece'])['knobs'].get(key)
    if not rule:
        return None
    if any(rule.get(ref) for ref in ('part', 'hinge', 'terminal', 'power_port', 'point')):
        return None
    name = f'your {p["piece"]} {index + 1}'
    mine = [q for q in compiled['parts'] if owner(q) == name and not q['name'].endswith(' stand')]
    if not mine:
        return None
    guide = {'key': key, 'label': rule.get('label', key), 'arrows': [], 'focus': [], 'marker': None}
    if key == 'end':
        # A track's physical board, including its compiled turn and elevation.
        board = next((q for q in mine if q['name'] == name), mine[0])
        solid = mw.solids_of(board)[0]
        axes, half = mw._axes(solid), mw._half(solid)
        guide['marker'] = [solid['at_m'][i] + axes[0][i] * half[0] + axes[1][i] * half[1] for i in range(3)]
        guide['focus'] = [q['name'] for q in mine if q['name'].endswith((' stop', ' barrier'))]
        return guide
    value = p[key]
    choices = rule.get('choices')
    if choices:
        candidate = next((v for v in choices if v != value), value)
    elif 'min' not in rule or 'max' not in rule:
        guide['focus'] = [q['name'] for q in mine]
        return guide
    else:
        step = max(rule.get('step', .01), (rule['max'] - rule['min']) * .05)
        candidate = min(rule['max'], value + step)
        if candidate == value:
            candidate = max(rule['min'], value - step)
    if candidate == value:
        guide['focus'] = [q['name'] for q in mine]
        return guide
    alternative = [{k: copy.deepcopy(v) for k, v in q.items() if k != 'cost'} for q in checked]
    alternative[index][key] = candidate
    try:
        _, _, _, probe = _assemble(level, alternative, lenient=True)
    except (ValueError, mw.MachineRefused):
        # A boundary adjustment can be unbuildable; the current fit verdict
        # stays authoritative and the control still identifies its piece.
        guide['focus'] = [q['name'] for q in mine]
        return guide
    other = {q['name']: q for q in probe['parts'] if owner(q) == name}
    increasing = isinstance(value, (int, float)) and isinstance(candidate, (int, float))
    sign = -1 if increasing and candidate < value else 1
    moves = []
    for q in mine:
        after = other.get(q['name'])
        if not after or after == q:
            continue
        guide['focus'].append(q['name'])
        for before, changed in zip(mw.solids_of(q), mw.solids_of(after)):
            a_axes, a_half = mw._axes(before), mw._half(before)
            b_axes, b_half = mw._axes(changed), mw._half(changed)
            resizing = before['turn_deg'] == changed['turn_deg'] and before['size_m'] != changed['size_m']
            for axis in range(3):
                if resizing and abs(a_half[axis] - b_half[axis]) < 1e-8:
                    continue
                for side in (-1, 1):
                    at = [before['at_m'][i] + side * a_axes[axis][i] * a_half[axis] for i in range(3)]
                    to = [changed['at_m'][i] + side * b_axes[axis][i] * b_half[axis] for i in range(3)]
                    d = [sign * (to[i] - at[i]) for i in range(3)]
                    distance = math.sqrt(sum(v * v for v in d))
                    if resizing and distance > .001:
                        # Show growth along the changed dimension, rather
                        # than a second arrow for re-seating a tilted body.
                        d = [sign * side * a_axes[axis][i] * (b_half[axis] - a_half[axis]) for i in range(3)]
                        distance = math.sqrt(sum(v * v for v in d))
                    if distance > .001:
                        moves.append((distance, at, [v / distance for v in d]))
    # One arrow per direction; favour the actual moving end over the centre
    # and avoid repeated arrows on the rails, supports and neighbouring faces.
    largest = max((row[0] for row in moves), default=0)
    for distance, at, direction in sorted(moves, key=lambda row: -row[0]):
        if distance < largest * .25:
            continue
        if any(sum(a * b for a, b in zip(direction, old['direction'])) > .9 for old in guide['arrows']):
            continue
        guide['arrows'].append({'at': at, 'direction': direction})
        if len(guide['arrows']) == 4:
            break
    if not guide['focus']:
        guide['focus'] = [q['name'] for q in mine]
    return guide


def ghost(level, placements, index, snapping=False, edit_key=None):
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
    reply = {'name': name, 'cost': checked[index]['cost'], 'problems': problems[:4], 'fits': not problems, 'sun': sun,
             'energy': pieces_energy(compiled).get(name),
             'parts': [dict({k: p[k] for k in keys if k in p},
                            **({'parts': p['parts']} if p['shape'] == 'compound' else {})) for p in mine]}
    # Draw the compiled terminals while placing a device, including its
    # prepared socket leads. This does not advance the engine.
    if checked[index]['piece'] in ('battery', 'switch', 'bulb', 'motor', 'ignition', 'wire', 'cannon'):
        reply['electrical_preview'] = compiled.get('electrical', {})
    if checked[index]['piece'] == 'wire':
        terminals = {device['name'] + ':' + key: at for device in compiled.get('electrical', {}).get('devices', [])
                     for key, at in device['terminals'].items()}
        wire = next((wire for wire in compiled.get('electrical', {}).get('wires', []) if wire['name'] == name), None)
        if wire:
            reply['wire_preview'] = [terminals[wire['a']], terminals[wire['b']]]
    if checked[index]['piece'] == 'power_cable':
        power_ports = {p['name']: p['at_m'] for p in compiled.get('electrical', {}).get('power_ports', [])}
        cable = next((c for c in compiled.get('electrical', {}).get('power_cables', []) if c['name'] == name), None)
        if cable:
            reply['wire_preview'] = [power_ports[cable['a']], power_ports[cable['b']]]
    if isinstance(edit_key, str):
        reply['edit_guide'] = editing_guide(level, checked, index, compiled, edit_key)
    if level.get('free'):
        # Where the other pieces connect, and where this one would.
        reply['ports'] = [q for q in ports(checked, compiled) if q['piece'] != index]
        found = snap(level, checked, index, compiled)
        if found:
            tray = next(t for t in level['tray'] if t['piece'] == checked[index]['piece'])
            knobs = {k: v for k, v in found['knobs'].items() if k in tray['knobs']}
            # Within half a slider step is where it is: the page sets knobs on their steps.
            moved = any(abs(knobs[k] - checked[index].get(k, 0.0)) > 0.006 for k in knobs)
            reply['snap'] = dict(found, knobs=knobs, moved=moved)
            if not snapping and moved:
                reply.pop('snap')      # only a piece being moved by hand is snapped
    return reply


def compose(level, placements, leave_out_goal=False):
    """The level's machine with the player's pieces in it, and the goal as a
    station. Raises LevelRefused (the tray) or mw.MachineRefused (the
    machine: overlaps, nothing in the ground, ...). A goal about a piece
    not placed yet is refused -- or with leave_out_goal, left out, and what
    it needs said in spec['_needs'], so the level can still be shown."""
    spec, checked, cost, compiled = _assemble(level, placements)
    names = {p['name'] for p in compiled['parts']}
    clashes = clashes_of(compiled)
    if clashes:
        raise LevelRefused(clashes[:4])
    if not level.get('goal'):
        spec.setdefault('stations', [])
        return spec, checked, cost      # sandbox readings are retained, never scored
    spec['stations'] = []
    goal = level['goal']['station']['done_when']
    available = names | {j['name'] for j in compiled['joints']} | {c['name'] for c in compiled['circuits']} \
        | {b['name'] for b in compiled['batteries']} | {s['name'] for s in compiled.get('spouts', [])} \
        | {d['name'] for d in compiled.get('electrical', {}).get('devices', [])} \
        | {s['name'] for s in (compiled.get('light') or {}).get('photocells', [])}
    missing = [name for name in _named(goal) if name not in available]
    if missing:
        wanted = missing[0]
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
            out += [value[k] for k in ('part', 'joint', 'photocell', 'battery', 'device', 'spout') if isinstance(value.get(k), str)]
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


def run_energy(compiled, readouts, t_s=0.0):
    """What came into the machine in its first t_s seconds, each once: what
    the batteries gave, as the engine measured it (a coil's heat, a laser's
    light and a motor's work all came out of a battery, and are counted
    there, not again where they ended up); fuel burned in its heaters (a
    firebox: its declared power for as long as it has burned); and the
    powder in its charges (all of it: a charge is there to be fired)."""
    start = {b['name']: b.get('charge_j', b['capacity_j']) for b in compiled.get('batteries') or []}
    stores = {b['name']: b for b in ((readouts or {}).get('machines') or {}).get('batteries') or []}
    drawn = sum(max(0.0, stores[n].get('given_j', start[n] - stores[n].get('charge_j', start[n])))
                for n in start if n in stores)
    heat = sum(h['power_w'] * min(h.get('seconds', 0.0), max(0.0, t_s - h.get('start_s', 0.0)))
               for h in (compiled.get('thermo') or {}).get('heaters') or [])
    parts = {p['name']: p for p in compiled['parts']}
    powder = 0.0
    for row in ((compiled.get('thermo') or {}).get('contents') or []):
        body = parts.get(row.get('body'))
        share = (row.get('contents') or {}).get('propellant', 0.0)
        if body and share:
            powder += _volume(body) * DENSITY.get(body['material'], 1000.0) * share * PROPELLANT_J_PER_KG
    # And a person's test pulls: the work they did on it (what pulled back on
    # them is theirs, not the machine's).
    pulled = sum(max(0.0, p.get('work_j') or 0.0) for p in (readouts or {}).get('pulls') or [])
    water = sum(max(0.0, source.get('source_energy_j') or 0.0)
                for source in ((readouts or {}).get('pour') or {}).get('sources', []))
    return {'heat_j': round(heat,3), 'powder_j': round(powder,3), 'electric_j': round(drawn,3),
            'pull_j': round(pulled,3), 'water_j': round(water,3), 'j': round(heat + powder + drawn + pulled + water,3)}


def energy_of(compiled, readouts, t_s=0.0):
    """The whole of it: the pieces' making and the run's energy in its first
    t_s seconds, itemised."""
    pieces = pieces_energy(compiled)
    run = run_energy(compiled, readouts, t_s)
    made = sum(v['j'] for v in pieces.values())
    return {'j': made + run['j'], 'pieces_j': made, 'pieces': pieces, 'run': run}


def measure_energy(level, placements, exe, logs, *, handle_inputs=None):
    """A rehearsal to the goal: when it happened and what the win took (a
    level's par is its own solution's)."""
    spec, _, _ = compose(level, placements)
    compiled = mw.compile_spec(spec)
    r = mw.rehearse(compiled, exe, logs, seconds=level['time_s'] + 0.3, wall_limit_s=120,
                    handle_inputs=handle_inputs)
    row = (r['stations'] or [{}])[0]
    return dict(energy_of(compiled, r.get('readouts'), r['world_time_s']),
                goal_at_s=row.get('at_s') if row.get('done') else None)


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


def trial(level, placements, exe, logs, runs=3, *, handle_inputs=None):
    """Run the machine `runs` times, nudged, and say in how many the goal
    happened in time. Unpaced: as fast as the engine goes."""
    spec, checked, cost = compose(level, placements)
    compiled = mw.compile_spec(spec)
    results = []
    for seed in range(runs):
        r = mw.rehearse(nudged(compiled, seed + 1) if seed else compiled, exe, logs,
                        seconds=level['time_s'] + 0.5, wall_limit_s=120, handle_inputs=handle_inputs)
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
    rule = next(iter(level['goal']['station']['done_when'].values())) if level.get('goal') else None
    wanted = rule.get('part') if isinstance(rule, dict) else rule
    loose = [p['name'] for p in compiled['parts'] if not p['fixed']]
    # With no goal, the marbles first: they are what a free build is about.
    loose.sort(key=lambda n: ' marble ' not in n + ' ')
    track = ([wanted] if wanted in loose else []) + [n for n in loose if n != wanted][:7]
    r = mw.rehearse(compiled, exe, logs, seconds=level['time_s'] + 0.3, wall_limit_s=wall_limit_s,
                    track=track, after_s=0.5, flows=bool(compiled.get('light') or compiled.get('spouts') or
                        (compiled.get('ground') or {}).get('kind') == 'flume' or
                        compiled.get('circuits') or compiled.get('electrical', {}).get('wires') or
                        compiled.get('electrical', {}).get('contacts') or
                        compiled.get('electrical', {}).get('power_cables')))
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
            'manual_input_required': bool(level.get('solution_inputs')),
            'flow_frames': r.get('flow_frames', []), 'complete': r.get('complete', not r['error']),
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
             if 'min' in rule and 'max' in rule and not rule.get('free')]
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
    result = {k: level[k] for k in ('id', 'title', 'brief', 'teaches', 'time_s', 'budget', 'par', 'style_pieces',
                                  'tray', 'goal', 'hints', 'par_energy_j', 'free', 'example', 'difficulty') if k in level}
    if not level.get('free'):
        family = level.get('variant', {}).get('family', level['id'])
        result['task_count'] = (1 if family == 'easy-solar' and level.get('variant', {}).get('version') == 1
                                else PLAYER_TASK_COUNTS[family])
    if level.get('variant'):
        result['variant'] = {k: level['variant'][k] for k in ('family', 'seed', 'version', 'attempt',
            'fallback', 'validated', 'parameter', 'parameter_label', 'kind', 'value', 'measured_energy_j') if k in level['variant']}
    return result
