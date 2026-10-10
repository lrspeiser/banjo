"""A machine world: one live engine world built from general parts.

A machine is a declaration (schema banjo.machine.v1) of parts, joints,
batteries, circuits and torches. Kits are shorthand that expand into exactly
those parts and joints: a domino row is boxes, a lever is a block, a plank and
a hinge. Nothing here decides an outcome. banjo_live_world_run steps every
body, contact, hinge, current and temperature; this module compiles the
declaration, refuses one the engine cannot build honestly (below the ground,
overlapping, missing names, too big), runs the engine against the wall clock
and reports what it measured. A new creation uses the same parts and laws as
the default machine; no part of it has a scripted outcome.
"""
from __future__ import annotations

import copy
import json
import math
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'banjo.machine.v1'
MATERIALS = ('glass', 'oak', 'iron', 'concrete', 'ceramic', 'ice', 'aluminum', 'rubber')
SHAPES = ('box', 'sphere', 'cone', 'compound')
SUB_SHAPES = ('box', 'cylinder')
JOINT_KINDS = ('hinge', 'fix', 'tie', 'spring', 'slide', 'drum', 'gear', 'pulley')
DT_S = 1.0 / 240.0
STEPS_PER_CALL = 4
# How long, in world time, a live machine lets a pair that is being worked
# out (a break or a dent, on the engine's worker) stay held while everything
# else moves on, before it waits for the answer.
MAX_HOLD_S = 0.05
MAX_PARTS = 120
MAX_TIME_S = 120.0
# Engine cell edges are 10-40 mm; the world's matter is built from cells this
# size, so nothing can be thinner than one.
CELL_CHOICES = (0.02, 0.04)
MAX_CELLS = 120_000
WORLD_HALF_M = 20.0
WORLD_TOP_M = 10.0
OVERLAP_TOLERANCE_M = 1.0e-3


class MachineRefused(ValueError):
    """The declaration cannot be built honestly; `problems` says why, in words."""

    def __init__(self, problems):
        super().__init__('; '.join(problems))
        self.problems = list(problems)


# ---- small vector helpers -------------------------------------------------

def _vec(value, n, what, problems):
    if not isinstance(value, (list, tuple)) or len(value) != n or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value):
        problems.append(f'{what} needs {n} finite numbers')
        return [0.0] * n
    return [float(v) for v in value]


def _num(d, key, what, problems, default=None, low=None, high=None):
    if key not in d or d[key] is None:
        if default is None:
            problems.append(f'{what} needs {key}')
            return 0.0
        return float(default)
    v = d[key]
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        problems.append(f'{what}: {key} must be a number')
        return float(default or 0.0)
    v = float(v)
    if (low is not None and v < low) or (high is not None and v > high):
        problems.append(f'{what}: {key} {v:g} is outside {low:g} to {high:g}')
    return v


def rotation(turn_deg):
    """The engine's turn of a body by turn_deg (TileImpactScene
    rotationQuaternion, which the engine reports back as the body's
    orientation): about the body's own x, then its own y, then its own z --
    which is about the world's z first, then y, then x: R = Rx Ry Rz.

    (TileImpactScene rotateDegrees turns the other way round, x first; with the
    angles negated it undoes a body's turn, and that is all it is for. This
    was built from it until October 10, 2026, which is the same for a turn
    about one axis and not for a turn about two.)"""
    rx, ry, rz = (math.radians(a) for a in turn_deg)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    mx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    my = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    mz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    return _mat_mul(mx, _mat_mul(my, mz))


def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mat_apply(m, v):
    return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]


def turn_of(m):
    """The turn_deg of a rotation matrix (R = Rx Ry Rz, as rotation()).
    Turned straight up or down by y, a turn about x and one about z are the
    same turn; it is then all put in x."""
    s = max(-1.0, min(1.0, m[0][2]))
    ry = math.asin(s)
    if math.hypot(m[0][0], m[0][1]) < 1e-9:
        rx, rz = math.atan2(math.copysign(1.0, s) * m[1][0], m[1][1]), 0.0
    else:
        rx, rz = math.atan2(-m[1][2], m[2][2]), math.atan2(-m[0][1], m[0][0])
    return [round(math.degrees(a), 6) + 0.0 for a in (rx, ry, rz)]


def heading(yaw_deg, pitch_deg, roll_deg):
    """A thing turned as a whole, the way a person turns it in their hands:
    about the vertical by yaw (a positive turn takes +x toward -z), then its
    +x end up by pitch, then about its own length (x) by roll. R = Ry Rz Rx."""
    return _mat_mul(rotation([0.0, yaw_deg, 0.0]), _mat_mul(rotation([0.0, 0.0, pitch_deg]),
                                                           rotation([roll_deg, 0.0, 0.0])))


# What a kit's rows hold that a turn moves: points turn about the pivot,
# directions turn with it, a part's own turn comes after it. A gas region
# that gives no axis grows up and vents down (ThermoWorld's defaults), so a
# turned one is given them, turned.
TURN_POINTS = ('at_m', 'at_b_m', 'over_a_m', 'over_b_m', 'centre_m', 'load_point_m', 'heel_m', 'tip_m')
TURN_DIRECTIONS = ('axis', 'vent_axis', 'facing', 'direction', 'normal', 'velocity_m_s')
GAS_DEFAULTS = {'axis': [0.0, 1.0, 0.0], 'vent_axis': [0.0, -1.0, 0.0]}


def _is_vec3(v):
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)


def turn_rows(m, about, parts, rows=()):
    """Turn a kit -- its parts and the joints, gas, edges and lamps it made --
    as one rigid thing by the matrix m about the point `about`."""
    def point(v):
        r = _mat_apply(m, [v[i] - about[i] for i in range(3)])
        return [round(about[i] + r[i], 6) for i in range(3)]

    def direction(v):
        return [round(x, 9) for x in _mat_apply(m, v)]
    for row in list(parts) + list(rows):
        if not isinstance(row, dict):
            continue
        if 'piston' in row:
            for key, default in GAS_DEFAULTS.items():
                row.setdefault(key, list(default))
        for key in TURN_POINTS + (('facing',) if 'facing_from' in row else ()) + ('facing_from',):
            if _is_vec3(row.get(key)):
                row[key] = point(row[key])
        for key in TURN_DIRECTIONS:
            if key == 'facing' and 'facing_from' in row:
                continue
            if _is_vec3(row.get(key)):
                row[key] = direction(row[key])
    for row in parts:
        if isinstance(row, dict):
            own = row.get('turn_deg') if _is_vec3(row.get('turn_deg')) else [0.0, 0.0, 0.0]
            row['turn_deg'] = turn_of(_mat_mul(m, rotation(own)))


def shift_rows(d, rows):
    """Move rows (as turn_rows takes them) by d, without turning them."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in TURN_POINTS + ('facing_from',) + (('facing',) if 'facing_from' in row else ()):
            if _is_vec3(row.get(key)):
                row[key] = [round(row[key][i] + d[i], 6) for i in range(3)]


def _ground_deficit(parts, ground):
    """How far the lowest of these parts goes below the ground under it (0
    when none does): what a turned thing is lifted by to stand on it."""
    worst = 0.0
    for p in parts:
        if not isinstance(p, dict) or not _is_vec3(p.get('at_m')) or not _is_vec3(p.get('size_m')):
            continue
        if p.get('shape') == 'sphere':
            r = 0.5 * p['size_m'][0]
            pts = [[p['at_m'][0], p['at_m'][1] - r, p['at_m'][2]]]
        elif p.get('shape', 'box') == 'box':
            pts = footprint_points(dict(p, turn_deg=p.get('turn_deg', [0, 0, 0])))
        else:
            continue
        worst = max([worst] + [ground_height(ground, pt[0], pt[2]) - pt[1] for pt in pts])
    return worst


def _axes(part):
    r = rotation(part['turn_deg'])
    return [[r[0][j], r[1][j], r[2][j]] for j in range(3)]


def _half(part):
    return [0.5 * s for s in part['size_m']]


def lowest_point(part):
    if part['shape'] == 'sphere':
        return part['at_m'][1] - 0.5 * part['size_m'][0]
    axes, h = _axes(part), _half(part)
    return part['at_m'][1] - sum(abs(axes[j][1]) * h[j] for j in range(3))


def _sphere_box(sphere, box):
    axes, h = _axes(box), _half(box)
    d = [sphere['at_m'][i] - box['at_m'][i] for i in range(3)]
    local = [sum(axes[j][k] * d[k] for k in range(3)) for j in range(3)]
    outside = [max(0.0, abs(local[j]) - h[j]) for j in range(3)]
    gap = math.sqrt(sum(x * x for x in outside))
    if gap == 0.0:   # centre inside the box: depth to the nearest face plus the radius
        return 0.5 * sphere['size_m'][0] + min(h[j] - abs(local[j]) for j in range(3))
    return 0.5 * sphere['size_m'][0] - gap


def overlap_depth(a, b):
    """How far two parts interpenetrate (positive) or how far apart they are
    (negative). Spheres are exact; boxes and cones use a separating-axis test
    on their oriented boxes."""
    if a['shape'] == 'sphere' and b['shape'] == 'sphere':
        return 0.5 * a['size_m'][0] + 0.5 * b['size_m'][0] - math.dist(a['at_m'], b['at_m'])
    if a['shape'] == 'sphere':
        return _sphere_box(a, b)
    if b['shape'] == 'sphere':
        return _sphere_box(b, a)
    ca, cb = a['at_m'], b['at_m']
    aa, ab = _axes(a), _axes(b)
    ha, hb = _half(a), _half(b)
    d = [cb[i] - ca[i] for i in range(3)]
    candidates = aa + ab
    for u in aa:
        for v in ab:
            c = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            n = math.sqrt(sum(x * x for x in c))
            if n > 1e-9:
                candidates.append([x / n for x in c])
    best = math.inf
    for axis in candidates:
        ra = sum(ha[j] * abs(sum(aa[j][k] * axis[k] for k in range(3))) for j in range(3))
        rb = sum(hb[j] * abs(sum(ab[j][k] * axis[k] for k in range(3))) for j in range(3))
        dist = abs(sum(d[k] * axis[k] for k in range(3)))
        best = min(best, ra + rb - dist)
        if best < 0:
            return best
    return best


# ---- the ground ----------------------------------------------------------------

def compile_ground(g, problems):
    """None (a level floor at y = 0), or a flume: level ground at y = 0 with a
    straight trench of water along x (src/terrain TerrainGenerator flume)."""
    if g is None:
        return None
    if not isinstance(g, dict) or g.get('kind') != 'flume':
        problems.append('ground is null (a level floor) or {"kind": "flume", ...}')
        return None
    what = 'ground'
    out = {'kind': 'flume',
           'nx': int(_num(g, 'nx', what, problems, 100, 20, 400)), 'nz': int(_num(g, 'nz', what, problems, 60, 20, 400)),
           'cell_m': _num(g, 'cell_m', what, problems, 0.1, 0.05, 0.25),
           'trench_z_m': _num(g, 'trench_z_m', what, problems, 1.0, -10, 10),
           'trench_width_m': _num(g, 'trench_width_m', what, problems, 0.5, 0.2, 3.0),
           'trench_depth_m': _num(g, 'trench_depth_m', what, problems, 0.35, 0.1, 2.0),
           'trench_slope': _num(g, 'trench_slope', what, problems, 0.005, 0.0, 0.05),
           'discharge_m3_s': _num(g, 'discharge_m3_s', what, problems, 0.0, 0.0, 1.0),
           'reservoir_to_x_m': _num(g, 'reservoir_to_x_m', what, problems, -1e9, -1e9, 100),
           'reservoir_level_m': _num(g, 'reservoir_level_m', what, problems, -1e9, -1e9, 0.0)}
    out['x0_m'] = -0.5 * (out['nx'] - 1) * out['cell_m']
    out['z0_m'] = -0.5 * (out['nz'] - 1) * out['cell_m']
    if abs(out['trench_z_m']) + 0.5 * out['trench_width_m'] + out['cell_m'] >= -out['z0_m']:
        problems.append('ground: the trench must lie inside the ground with ground on both sides')
    return out


def ground_height(ground, x, z):
    if ground is None:
        return 0.0
    if abs(z - ground['trench_z_m']) <= 0.5 * ground['trench_width_m']:
        return -ground['trench_depth_m'] - ground['trench_slope'] * (x - ground['x0_m'])
    return 0.0


def ground_scene(ground):
    keys = ('nx', 'nz', 'cell_m', 'trench_z_m', 'trench_width_m', 'trench_depth_m', 'trench_slope', 'discharge_m3_s')
    generate = {'kind': 'flume', **{k: ground[k] for k in keys}}
    if ground['reservoir_level_m'] > -1e8:
        generate['reservoir_to_x_m'] = ground['reservoir_to_x_m']
        generate['reservoir_level_m'] = ground['reservoir_level_m']
    return {'generate': generate}


def quaternion_of_turn(degrees):
    """TileImpactScene rotationQuaternion: about x, then y, then z."""
    hx, hy, hz = (math.radians(d) / 2 for d in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(hx), math.sin(hx), math.cos(hy), math.sin(hy), math.cos(hz), math.sin(hz)
    return [cz * cy * cx - sz * sy * sx, cz * cy * sx + sz * sy * cx, cz * sy * cx - sz * cy * sx,
            sz * cy * cx + cz * sy * sx]


def solids_of(part):
    """A part as the oriented boxes it is made of, in the world: itself, or
    each piece of a compound (a cylinder as its bounding box)."""
    if part['shape'] != 'compound':
        return [part]
    outer = rotation(part['turn_deg'])
    out = []
    for sub in part['parts']:
        local = sub['at_m']
        at = [part['at_m'][i] + sum(outer[i][j] * local[j] for j in range(3)) for i in range(3)]
        size = list(sub['size_m'])
        if sub['shape'] == 'cylinder':   # [diameter, length, diameter] about its own y
            size = [size[0], size[1], size[0]]
        out.append({'name': part['name'], 'shape': 'box', 'size_m': size, 'at_m': at,
                    'turn_deg': turn_of(_mat_mul(outer, rotation(sub['turn_deg'])))})
    return out


def footprint_points(solid):
    axes, h = _axes(solid), _half(solid)
    pts = []
    for sx in (-1, 0, 1):
        for sz in (-1, 0, 1):
            for sy in (-1, 1):
                pts.append([solid['at_m'][i] + sx * axes[0][i] * h[0] + sy * axes[1][i] * h[1] + sz * axes[2][i] * h[2]
                            for i in range(3)])
    return pts


# ---- kits: shorthand for parts and joints -----------------------------------

def _dir(word, problems, what):
    table = {'+x': (1, 0, 0), '-x': (-1, 0, 0), '+z': (0, 0, 1), '-z': (0, 0, -1)}
    if word not in table:
        problems.append(f'{what}: direction must be one of +x, -x, +z, -z')
        return (1, 0, 0)
    return table[word]


def _kit_ramp(k, problems, name):
    """An anchored plank from `top_m` down to `bottom_m` (the centre of its
    upper surface at each end), with side rails, and optionally a ball resting
    at the top. Gravity and contact friction decide whether it rolls."""
    top = _vec(k.get('top_m'), 3, name + ' top_m', problems)
    bottom = _vec(k.get('bottom_m'), 3, name + ' bottom_m', problems)
    width = _num(k, 'width_m', name, problems, 0.2, 0.06, 2.0)
    thick = _num(k, 'thickness_m', name, problems, 0.04, 0.02, 0.4)
    mat = k.get('material', 'oak')
    dx, dy, dz = (bottom[i] - top[i] for i in range(3))
    # A ramp runs along x or along z. (The engine turns a body about x, then
    # y, then z, so a tilt along a diagonal would need a turn order it does
    # not take; two ramps at right angles make a corner instead.)
    along_x = abs(dx) >= abs(dz)
    if abs(dz if along_x else dx) > 0.01:
        problems.append(name + ': a ramp runs along x or z; make top_m and bottom_m differ in only one of them')
    run = abs(dx if along_x else dz)
    length = math.hypot(run, dy)
    if length < 0.2:
        problems.append(name + ': a ramp is at least 0.2 m long')
        length = max(length, 0.2)
    if dy >= 0:
        problems.append(name + ': bottom_m must be lower than top_m')
    slope = math.degrees(math.atan2(-dy, max(run, 1e-9)))
    if slope > 60:
        problems.append(name + ': a ramp is at most 60 degrees')
    sign = 1.0 if (dx if along_x else dz) >= 0 else -1.0
    along = [sign * run / length if along_x else 0.0, dy / length, 0.0 if along_x else sign * run / length]
    side = [0.0, 0.0, 1.0] if along_x else [1.0, 0.0, 0.0]
    # Surface normal: side x along, turned to point up.
    normal = [side[1] * along[2] - side[2] * along[1], side[2] * along[0] - side[0] * along[2],
              side[0] * along[1] - side[1] * along[0]]
    if normal[1] < 0:
        normal = [-v for v in normal]
    if along_x:   # long axis is local x; tip it about z
        size, turn = [length, thick, width], [0.0, 0.0, -sign * slope]
    else:         # long axis is local z; tip it about x
        size, turn = [width, thick, length], [sign * slope, 0.0, 0.0]
    mid_top = [(top[i] + bottom[i]) / 2 for i in range(3)]
    centre = [mid_top[i] - normal[i] * 0.5 * thick for i in range(3)]
    parts = [{'name': name, 'shape': 'box', 'material': mat, 'size_m': size, 'at_m': centre, 'turn_deg': turn,
              'fixed': True}]
    if k.get('rails', True):
        rail_h, rail_w = 0.06, 0.04
        for tag, s in (('left', 1), ('right', -1)):
            off = 0.5 * width + 0.5 * rail_w
            rsize = [length, rail_h, rail_w] if along_x else [rail_w, rail_h, length]
            parts.append({'name': f'{name} {tag} rail', 'shape': 'box', 'material': mat, 'size_m': rsize,
                          'at_m': [centre[i] + s * off * side[i] + normal[i] * (0.5 * thick + 0.5 * rail_h)
                                   for i in range(3)],
                          'turn_deg': turn, 'fixed': True})
    ball = k.get('ball')
    joints = []
    if isinstance(ball, dict):
        dia = _num(ball, 'diameter_m', name + ' ball', problems, 0.08, 0.04, min(0.6, width))
        start = 0.08 + 0.5 * dia
        at = [top[i] + along[i] * start + normal[i] * (0.5 * dia + 0.002) for i in range(3)]
        parts.append({'name': ball.get('name') or name + ' ball', 'shape': 'sphere',
                      'material': ball.get('material', 'iron'), 'size_m': [dia, dia, dia], 'at_m': at,
                      'turn_deg': [0, 0, 0], 'fixed': False})
        if k.get('gate'):
            # A bar across the ramp just below the ball, free to slide sideways
            # in a guide: whatever pulls it far enough lets the ball go.
            if k.get('rails', True):
                problems.append(name + ': a gated ramp has no rails (the gate slides across where they would be)')
            bar = 0.04
            gate_at = [top[i] + along[i] * (start + 0.5 * dia + 0.01 + 0.5 * bar) + normal[i] * (0.5 * bar + 0.006)
                       for i in range(3)]
            length = width + 0.3
            gsize = [bar, bar, length] if along_x else [length, bar, bar]
            parts.append({'name': name + ' gate', 'shape': 'box', 'material': 'oak', 'size_m': gsize, 'at_m': gate_at,
                          'turn_deg': turn, 'fixed': False})
            guide_at = [gate_at[i] + side[i] * (0.5 * length + 0.25) for i in range(3)]
            guide_at[1] = gate_at[1] - 0.15
            parts.append({'name': name + ' gate guide', 'shape': 'box', 'material': 'concrete',
                          'size_m': [0.06, 0.06, 0.06], 'at_m': guide_at, 'turn_deg': [0, 0, 0], 'fixed': True})
            joints.append({'name': name + ' gate slide', 'kind': 'slide', 'a': name + ' gate guide', 'b': name + ' gate',
                           'at_m': gate_at, 'axis': side, 'lower_m': 0.0,
                           'upper_m': 0.5 * length + dia + 0.08, 'friction_n': 1.0})
    return parts, joints


def _kit_domino_row(k, problems, name):
    start = _vec(k.get('start_m'), 3, name + ' start_m', problems)
    d = _dir(k.get('direction', '+x'), problems, name)
    count = int(_num(k, 'count', name, problems, 8, 1, 40))
    spacing = _num(k, 'spacing_m', name, problems, 0.2, 0.05, 1.0)
    size = _vec(k.get('size_m', [0.04, 0.4, 0.24]), 3, name + ' size_m', problems)
    mat = k.get('material', 'oak')
    turn = [0.0, 0.0 if d[0] else 90.0, 0.0]
    parts = []
    for i in range(count):
        at = [start[0] + d[0] * spacing * i, start[1] + 0.5 * size[1], start[2] + d[2] * spacing * i]
        parts.append({'name': f'{name} {i + 1}', 'shape': 'box', 'material': mat, 'size_m': list(size),
                      'at_m': at, 'turn_deg': turn, 'fixed': False})
    return parts, []


def _kit_lever(k, problems, name):
    """A block, a plank one engine cell above it so nothing rubs, and a hinge
    through the plank's middle. The plank turns only as forces on it say."""
    at = _vec(k.get('pivot_m'), 3, name + ' pivot_m', problems)   # x, top of block height, z
    length = _num(k, 'length_m', name, problems, 0.8, 0.2, 4.0)
    width = _num(k, 'width_m', name, problems, 0.2, 0.04, 1.0)
    thick = _num(k, 'thickness_m', name, problems, 0.04, 0.02, 0.3)
    limit = _num(k, 'limit_deg', name, problems, 15, 1, 80)
    gap = _num(k, 'gap_m', name, problems, 0.02, 0.01, 0.2)
    along = k.get('along', 'x')
    if along not in ('x', 'z'):
        problems.append(name + ': along is x or z')
    turn = [0.0, 0.0 if along == 'x' else 90.0, 0.0]
    block_h = at[1]
    if block_h < 0.04:
        problems.append(name + ': the pivot block is at least 0.04 m tall')
    plank_y = block_h + gap + 0.5 * thick
    parts = [{'name': name + ' pivot', 'shape': 'box', 'material': k.get('pivot_material', 'concrete'),
              'size_m': [0.12, max(block_h, 0.04), width + 0.04], 'at_m': [at[0], 0.5 * max(block_h, 0.04), at[2]],
              'turn_deg': turn, 'fixed': True},
             {'name': name, 'shape': 'box', 'material': k.get('material', 'oak'), 'size_m': [length, thick, width],
              'at_m': [at[0], plank_y, at[2]], 'turn_deg': turn, 'fixed': False}]
    joints = [{'name': name + ' hinge', 'kind': 'hinge', 'a': name + ' pivot', 'b': name,
               'at_m': [at[0], plank_y, at[2]], 'axis': [0, 0, 1] if along == 'x' else [1, 0, 0],
               'lower_deg': -limit, 'upper_deg': limit,
               'friction_n_m': _num(k, 'friction_n_m', name, problems, 0.5, 0, 50)}]
    return parts, joints


def _kit_hanging_weight(k, problems, name):
    """A post, a peg in it, and a weight hung from the peg. The peg's fixing to
    the post is MADE of the peg: when heat weakens the peg, what the fixing
    can carry falls, and it parts when the weight's pull exceeds it."""
    at = _vec(k.get('post_m'), 3, name + ' post_m', problems)   # x, ignored, z of the post foot
    drop = _num(k, 'drop_m', name, problems, 1.2, 0.2, 6.0)
    peg = _num(k, 'peg_size_m', name, problems, 0.02, 0.02, 0.1)
    wsize = _num(k, 'weight_size_m', name, problems, 0.16, 0.04, 0.6)
    side = _dir(k.get('side', '+z'), problems, name)
    holds = _num(k, 'holds_shear_n', name, problems, 800, 10, 1e6)
    peg_len = _num(k, 'peg_length_m', name, problems, 0.3, 0.1, 1.0)
    post_w = 0.16
    hang = k.get('hang', 'peg')
    if hang not in ('peg', 'rope'):
        problems.append(f'{name}: hang is "peg" or "rope"')
    if hang == 'rope':
        # A rope -- an oak cord, there being no fibre material yet -- hanging
        # from a fixed arm at the top of the post, the weight on its lower end.
        # The rope's fixing to the arm is made of the rope: heat weakens it
        # and it parts in tension when it can no longer carry the weight.
        rope = _num(k, 'rope_m', name, problems, 0.3, 0.1, 2.0)
        thick = peg
        reach = 0.5 * peg_len + 0.005
        post_h = drop + wsize + 0.005 + rope + 0.005 + 0.04
        x = at[0] + side[0] * (0.5 * post_w + reach)
        z = at[2] + side[2] * (0.5 * post_w + reach)
        arm_len = reach + 0.03
        arm_c = [at[0] + side[0] * (0.5 * post_w + 0.5 * arm_len), post_h - 0.02,
                 at[2] + side[2] * (0.5 * post_w + 0.5 * arm_len)]
        rope_top = post_h - 0.04 - 0.005
        rope_c = [x, rope_top - 0.5 * rope, z]
        weight_c = [x, drop + 0.5 * wsize, z]
        arm_size = [arm_len if side[0] else 0.06, 0.04, arm_len if side[2] else 0.06]
        parts = [{'name': name + ' post', 'shape': 'box', 'material': k.get('post_material', 'concrete'),
                  'size_m': [post_w, post_h, post_w], 'at_m': [at[0], 0.5 * post_h, at[2]], 'turn_deg': [0, 0, 0],
                  'fixed': True},
                 {'name': name + ' arm', 'shape': 'box', 'material': k.get('post_material', 'concrete'),
                  'size_m': arm_size, 'at_m': arm_c, 'turn_deg': [0, 0, 0], 'fixed': True},
                 {'name': name + ' rope', 'shape': 'box', 'material': k.get('peg_material', 'oak'),
                  'size_m': [thick, rope, thick], 'at_m': rope_c, 'turn_deg': [0, 0, 0], 'fixed': False},
                 {'name': name, 'shape': 'box', 'material': k.get('weight_material', 'iron'),
                  'size_m': [wsize, wsize, wsize], 'at_m': weight_c, 'turn_deg': [0, 0, 0], 'fixed': False}]
        joints = [{'name': name + ' rope fixing', 'kind': 'fix', 'a': name + ' arm', 'b': name + ' rope',
                   'at_m': [x, rope_top, z], 'axis': [0.0, 1.0, 0.0],
                   'holds_tension_n': _num(k, 'holds_tension_n', name, problems, holds, 10, 1e6),
                   'member': name + ' rope'},
                  {'name': name + ' hook', 'kind': 'fix', 'a': name + ' rope', 'b': name,
                   'at_m': [x, rope_top - rope, z], 'axis': [0, 1, 0]}]
        return parts, joints
    # So the weight's underside is drop_m above the ground.
    post_h = drop + 0.2 + 0.5 * peg + wsize + 0.005
    peg_c = [at[0] + side[0] * (0.5 * post_w + 0.5 * peg_len + 0.005), post_h - 0.2,
             at[2] + side[2] * (0.5 * post_w + 0.5 * peg_len + 0.005)]
    weight_c = [peg_c[0], peg_c[1] - 0.5 * peg - 0.5 * wsize - 0.005, peg_c[2]]
    turn = [0.0, 0.0 if side[2] else 90.0, 0.0]
    parts = [{'name': name + ' post', 'shape': 'box', 'material': k.get('post_material', 'concrete'),
              'size_m': [post_w, post_h, post_w], 'at_m': [at[0], 0.5 * post_h, at[2]], 'turn_deg': [0, 0, 0],
              'fixed': True},
             {'name': name + ' peg', 'shape': 'box', 'material': k.get('peg_material', 'oak'),
              'size_m': [peg, peg, peg_len], 'at_m': peg_c, 'turn_deg': turn, 'fixed': False},
             {'name': name, 'shape': 'box', 'material': k.get('weight_material', 'iron'),
              'size_m': [wsize, wsize, wsize], 'at_m': weight_c, 'turn_deg': [0, 0, 0], 'fixed': False}]
    face = [at[0] + side[0] * 0.5 * post_w, peg_c[1], at[2] + side[2] * 0.5 * post_w]
    joints = [{'name': name + ' peg fixing', 'kind': 'fix', 'a': name + ' post', 'b': name + ' peg', 'at_m': face,
               'axis': [float(side[0]), 0.0, float(side[2])], 'holds_shear_n': holds, 'member': name + ' peg'},
              {'name': name + ' hook', 'kind': 'fix', 'a': name + ' peg', 'b': name,
               'at_m': [peg_c[0], peg_c[1] - 0.5 * peg, peg_c[2]], 'axis': [0, 1, 0]}]
    return parts, joints


def _kit_plate(k, problems, name):
    at = _vec(k.get('at_m'), 3, name + ' at_m', problems)   # x, height of the plate's underside, z
    size = _vec(k.get('size_m', [0.48, 0.02, 0.56]), 3, name + ' size_m', problems)
    height = max(at[1], 0.06)
    span_along = k.get('span', 'z')
    sup_t = 0.08
    parts = []
    for tag, sign in (('A', -1), ('B', 1)):
        if span_along == 'z':
            centre = [at[0], 0.5 * height, at[2] + sign * (0.5 * size[2] - 0.5 * sup_t)]
            dims = [size[0] + 0.12, height, sup_t]
        else:
            centre = [at[0] + sign * (0.5 * size[0] - 0.5 * sup_t), 0.5 * height, at[2]]
            dims = [sup_t, height, size[2] + 0.12]
        parts.append({'name': f'{name} support {tag}', 'shape': 'box', 'material': k.get('support_material', 'concrete'),
                      'size_m': dims, 'at_m': centre, 'turn_deg': [0, 0, 0], 'fixed': True})
    parts.append({'name': name, 'shape': 'box', 'material': k.get('material', 'glass'), 'size_m': list(size),
                  'at_m': [at[0], height + 0.5 * size[1] + 0.002, at[2]], 'turn_deg': [0, 0, 0], 'fixed': False})
    return parts, []


def _kit_pendulum(k, problems, name):
    """A fixed frame (two posts and a beam), a rope from the beam, and a ball
    on it pulled back by an angle. Released at rest: gravity and the rope's
    tension decide the swing."""
    rope = _num(k, 'rope_m', name, problems, 0.6, 0.1, 4.0)
    pull = _num(k, 'pull_back_deg', name, problems, 45, 0, 85)
    d = _dir(k.get('swing_toward', '+x'), problems, name)
    ball = k.get('ball') if isinstance(k.get('ball'), dict) else {}
    dia = _num(ball, 'diameter_m', name + ' ball', problems, 0.12, 0.04, 0.5)
    aim = k.get('aim_at')
    if aim is not None:
        # Hang it so the ball's leading face meets the named part's near face
        # at the bottom of the swing, a little above that part's middle so a
        # stack topples. Only where it hangs is chosen; the engine decides
        # whether, and how hard, it hits.
        target = (k.get('_known') or {}).get(aim)
        if target is None:
            problems.append(f'{name}: aim_at must name a part declared before this kit ({aim!s} is not one)')
            pivot = [0.0, rope + dia, 0.0]
        else:
            axes, h = _axes(target), _half(target)
            reach = sum(abs(axes[j][0 if d[0] else 2]) * h[j] for j in range(3))
            height = sum(abs(axes[j][1]) * h[j] for j in range(3))
            centre = target['at_m']
            lead = 0.5 * dia + 0.004
            bottom = [centre[0] - d[0] * (reach + lead), centre[1] + 0.25 * height, centre[2] - d[2] * (reach + lead)]
            bottom[1] = max(bottom[1], 0.5 * dia + 0.02)
            pivot = [bottom[0], bottom[1] + rope, bottom[2]]
    else:
        pivot = _vec(k.get('pivot_m'), 3, name + ' pivot_m', problems)
    side = (0.0, 0.0, 1.0) if d[0] else (1.0, 0.0, 0.0)
    beam_t, half_span = 0.06, max(0.3, dia)
    s, c = math.sin(math.radians(pull)), math.cos(math.radians(pull))
    at = [pivot[0] - d[0] * rope * s, pivot[1] - rope * c, pivot[2] - d[2] * rope * s]
    if pivot[1] - rope - 0.5 * dia < 0.01:
        problems.append(f'{name}: the ball would hit the ground at the bottom of its swing; '
                        f'raise pivot_m above {rope + 0.5 * dia + 0.01:.2f} m or shorten the rope')
    beam_c = [pivot[0], pivot[1] + 0.5 * beam_t, pivot[2]]
    beam_size = [beam_t, beam_t, 2 * half_span + beam_t] if d[0] else [2 * half_span + beam_t, beam_t, beam_t]
    post_h = pivot[1] + beam_t
    frame = k.get('frame_material', 'oak')
    parts = [{'name': name + ' beam', 'shape': 'box', 'material': frame, 'size_m': beam_size, 'at_m': beam_c,
              'turn_deg': [0, 0, 0], 'fixed': True}]
    for tag, sgn in (('A', -1), ('B', 1)):
        parts.append({'name': f'{name} post {tag}', 'shape': 'box', 'material': frame,
                      'size_m': [beam_t, post_h, beam_t],
                      'at_m': [pivot[0] + sgn * side[0] * half_span, 0.5 * post_h, pivot[2] + sgn * side[2] * half_span],
                      'turn_deg': [0, 0, 0], 'fixed': True})
    parts.append({'name': ball.get('name') or name + ' ball', 'shape': 'sphere', 'material': ball.get('material', 'iron'),
                  'size_m': [dia, dia, dia], 'at_m': at, 'turn_deg': [0, 0, 0], 'fixed': False})
    joints = [{'name': name + ' rope', 'kind': 'tie', 'a': name + ' beam', 'b': parts[-1]['name'], 'at_m': pivot,
               'at_b_m': at, 'length_m': rope, 'breaks_at_n': _num(k, 'rope_breaks_at_n', name, problems, 0, 0, 1e7)}]
    return parts, joints


def _kit_block_tower(k, problems, name):
    at = _vec(k.get('at_m'), 3, name + ' at_m', problems)
    count = int(_num(k, 'count', name, problems, 3, 1, 20))
    size = _vec(k.get('size_m', [0.1, 0.1, 0.1]), 3, name + ' size_m', problems)
    gap = _num(k, 'gap_m', name, problems, 0.002, 0.0, 0.05)
    parts = []
    for i in range(count):
        y = at[1] + 0.5 * size[1] + i * (size[1] + gap)
        parts.append({'name': f'{name} {i + 1}', 'shape': 'box', 'material': k.get('material', 'oak'),
                      'size_m': list(size), 'at_m': [at[0], y, at[2]], 'turn_deg': [0, 0, 0], 'fixed': False})
    return parts, []


def _kit_water_wheel(k, problems, name):
    """A paddle wheel in the flume: one rigid body (hub, axle and paddles) on
    a hinge to a post on the bank. The stream's drag on each paddle, as the
    engine computes it per surface, is all that turns it."""
    ground = k.get('_ground')
    if ground is None:
        problems.append(name + ': a water wheel stands in the flume; declare ground {"kind": "flume", ...} first')
        return [], []
    at = _vec(k.get('at_m'), 3, name + ' at_m', problems)
    x, z = at[0], ground['trench_z_m']
    radius = _num(k, 'radius_m', name, problems, 0.4, 0.15, 1.5)
    count = int(_num(k, 'paddles', name, problems, 8, 3, 16))
    width = _num(k, 'paddle_width_m', name, problems, min(0.36, ground['trench_width_m'] - 0.14), 0.05, 2.0)
    clearance = _num(k, 'clearance_m', name, problems, 0.065, 0.02, 0.5)
    if width > ground['trench_width_m'] - 0.12:
        problems.append(f'{name}: paddles at most {ground["trench_width_m"] - 0.12:.2f} m wide in this trench')
    side = 1.0 if k.get('post_side', '+z') == '+z' else -1.0
    bed = ground_height(ground, x, z)
    hub_y = bed + clearance + radius
    hub_d = max(0.12, 0.55 * radius)
    reach = 0.5 * ground['trench_width_m'] + 0.25
    sub = [{'shape': 'cylinder', 'size_m': [0.06, reach + 0.05, 0.06], 'at_m': [0, 0, side * 0.5 * (reach - 0.05)],
            'turn_deg': [90, 0, 0]},
           {'shape': 'cylinder', 'size_m': [hub_d, width, hub_d], 'at_m': [0, 0, 0], 'turn_deg': [90, 0, 0]}]
    paddle_len = radius - 0.5 * hub_d + 0.02
    mid = 0.5 * hub_d - 0.02 + 0.5 * paddle_len
    for i in range(count):
        th = 360.0 * i / count
        sub.append({'shape': 'box', 'size_m': [paddle_len, 0.03, width],
                    'at_m': [mid * math.cos(math.radians(th)), mid * math.sin(math.radians(th)), 0],
                    'turn_deg': [0, 0, th]})
    post_h = max(0.12, hub_y + 0.06)
    parts = [{'name': name, 'shape': 'compound', 'material': k.get('material', 'oak'), 'size_m': [2 * radius] * 3,
              'at_m': [x, hub_y, z], 'turn_deg': [0, 0, 0], 'fixed': False, 'parts': sub},
             {'name': name + ' post', 'shape': 'box', 'material': 'concrete', 'size_m': [0.1, post_h, 0.1],
              'at_m': [x, 0.5 * post_h, z + side * (reach + 0.06)], 'turn_deg': [0, 0, 0], 'fixed': True}]
    joints = [{'name': name + ' hinge', 'kind': 'hinge', 'a': name + ' post', 'b': name, 'at_m': [x, hub_y, z],
               'axis': [0, 0, 1], 'friction_n_m': _num(k, 'friction_n_m', name, problems, 0.2, 0, 50)}]
    pour = k.get('pour')
    if pour is not None:
        # A spout above the paddles on one side of the axle: water poured on
        # the -x side turns the wheel toward +z (as the stream under it does),
        # on the +x side the other way.
        if not isinstance(pour, dict):
            problems.append(f'{name}: pour is an object')
            return parts, joints
        sx = {'-x': -1.0, '+x': 1.0}.get(pour.get('side', '-x'))
        if sx is None:
            problems.append(f'{name}: pour side is "-x" or "+x"')
            sx = -1.0
        offset = _num(pour, 'offset_m', name + ' pour', problems, 0.5 * radius, 0.05, radius)
        height = _num(pour, 'height_m', name + ' pour', problems, 0.5, 0.1, 3.0)
        mouth = [x + sx * offset, hub_y + radius + height, z]
        parts.append({'name': name + ' spout', 'shape': 'box', 'material': 'iron', 'size_m': [0.06, 0.1, 0.06],
                      'at_m': [mouth[0], mouth[1] + 0.08, z], 'turn_deg': [0, 0, 0], 'fixed': True})
        k['_spouts'].append({'name': name + ' spout', 'at_m': mouth, 'direction': [0, -1, 0],
                             'speed_m_s': _num(pour, 'speed_m_s', name + ' pour', problems, 1.0, 0, 10),
                             'discharge_l_s': _num(pour, 'discharge_l_s', name + ' pour', problems, 2.0, 0.1, 20),
                             'from_s': _num(pour, 'from_s', name + ' pour', problems, 0.0, 0, 600),
                             'until_s': pour.get('until_s')})
    return parts, joints


# Water boils at 373.15 K (the engine pins it there while any is left).
BOILING_K = 373.15
# The engine's densities (src/material/MaterialCatalog.cpp), for the kits that
# put so many kilograms of something into a part.
DENSITY_KG_M3 = {'iron': 7870.0, 'oak': 700.0, 'aluminum': 2700.0, 'concrete': 2400.0, 'ice': 917.0}
# What an edge can cut, from the same catalogue: a material with a yield point
# (the rest crack instead) and softer than the edge's own (an edge on
# something as hard flattens instead). Indentation hardness, Pa.
HARDNESS_PA = {'iron': 1.5e9, 'aluminum': 950e6, 'oak': 35e6, 'rubber': 6e6}


def cuttable(target, edge):
    """Whether an edge of material `edge` can cut material `target`."""
    return target in HARDNESS_PA and HARDNESS_PA[target] < HARDNESS_PA.get(edge, 0.0)


def _kit_steam_engine(k, problems, name):
    """A boiler, a cylinder and a piston: heat boils the boiler's water, the
    steam fills the gas under the piston and its pressure lifts the piston and
    whatever stands on it (the engine's thermochemistry, docs/thermal-
    mechanics.md). The cylinder is a solid block -- the engine's gas region is
    a volume of gas, not a hole -- and the piston sits on top of it."""
    at = _vec(k.get('at_m'), 3, name + ' at_m', problems)       # x, base height, z
    bore = _num(k, 'bore_m', name, problems, 0.24, 0.06, 0.6)
    tall = _num(k, 'cylinder_m', name, problems, 0.3, 0.1, 1.0)
    water = _num(k, 'water_kg', name, problems, 0.3, 0.005, 5.0)
    heat_w = _num(k, 'heat_w', name, problems, 10000.0, 0.0, 1e5)
    side = _dir(k.get('boiler_side', '-x'), problems, name + ' boiler_side')
    base, wall, box = max(at[1], 0.0), 0.03, 0.16
    width = bore + 2 * wall
    parts = [
        {'name': f'{name} cylinder', 'shape': 'box', 'material': 'iron', 'size_m': [width, tall, width],
         'at_m': [at[0], base + 0.5 * tall, at[2]], 'turn_deg': [0, 0, 0], 'fixed': True},
        {'name': f'{name} piston', 'shape': 'box', 'material': 'iron', 'size_m': [bore, 0.04, bore],
         'at_m': [at[0], base + tall + 0.022, at[2]], 'turn_deg': [0, 0, 0], 'fixed': False},
        {'name': f'{name} boiler', 'shape': 'box', 'material': 'iron', 'size_m': [box, box, box],
         'at_m': [at[0] + side[0] * (0.5 * width + 0.05 + 0.5 * box), base + 0.5 * box,
                  at[2] + side[2] * (0.5 * width + 0.05 + 0.5 * box)], 'turn_deg': [0, 0, 0], 'fixed': True}]
    boiler_kg = box ** 3 * DENSITY_KG_M3['iron']
    if water >= boiler_kg:
        problems.append(f'{name}: water_kg must be less than the boiler ({boiler_kg:.1f} kg)')
    region = f'{name} steam'
    thermo = k['_thermo']
    # Balanced: the gas starts holding the piston up, so what lifts it is the
    # steam the boiler makes, not a jump in pressure at the start.
    thermo['gas_regions'].append({'name': region, 'contents': {'nitrogen': 1.0}, 'piston': f'{name} piston',
                                  'container': f'{name} cylinder', 'balance': True, 'height_m': round(0.8 * tall, 4),
                                  'area_m2': round(bore * bore, 6), 'wall_conductance_w_k': 0.0})
    # The boiler's water is part of what the boiler is, by mass; the rest is
    # inert. It starts at its boiling point, as if the fire had been lit
    # before the machine was set going, so every joule in boils water.
    fraction = min(water / boiler_kg, 1.0)
    thermo['contents'].append({'body': f'{name} boiler', 'contents': {'water': round(fraction, 6),
                                                                      'ash': round(1.0 - fraction, 6)},
                               'temperature_k': BOILING_K, 'environment': region})
    if heat_w > 0:
        thermo['heaters'].append({'target': f'{name} boiler', 'power_w': heat_w,
                                  'start_s': _num(k, 'start_s', name, problems, 0.0, 0.0, 600.0),
                                  'seconds': _num(k, 'seconds', name, problems, 120.0, 0.1, 3600.0),
                                  'label': f'{name} firebox'})
    return parts, []


def _kit_cannon(k, problems, name):
    """A barrel, a ball at its muzzle and a powder charge behind it. When the
    charge is hot enough it burns, the gas in the breech pushes the ball out
    along the barrel and the barrel back (the engine's thermochemistry: the
    "propellant" is a stand-in for gunpowder, 2.8 MJ/kg, carrying its own
    oxygen). Lit by a primer at fire_at_s, or by a circuit's coil wound on
    "<name> charge". The ball sits at the muzzle -- a body cannot be inside
    another one here -- held by a wad (a fixing that parts when the breech
    pushes on it hard enough), and flies level."""
    at = _vec(k.get('at_m'), 3, name + ' at_m', problems)       # the muzzle: x, height of the bore's axis, z
    toward = _dir(k.get('toward', '+x'), problems, name + ' toward')
    length = _num(k, 'length_m', name, problems, 0.3, 0.1, 2.0)
    ball = k.get('ball') if isinstance(k.get('ball'), dict) else {}
    d = _num(ball, 'diameter_m', name + ' ball', problems, 0.08, 0.02, 0.2)
    material = ball.get('material', 'iron')
    powder_g = _num(k, 'powder_g', name, problems, 1.5, 0.01, 20.0)
    bore = d + 0.04
    axis_y = max(at[1], 0.5 * bore, 0.5 * d)
    along = [abs(toward[0]) > 0, abs(toward[2]) > 0]
    size = [length if along[0] else bore, bore, length if along[1] else bore]
    parts = [{'name': f'{name} barrel', 'shape': 'box', 'material': 'iron', 'size_m': size,
              'at_m': [at[0] - toward[0] * 0.5 * length, axis_y, at[2] - toward[2] * 0.5 * length],
              'turn_deg': [0, 0, 0], 'fixed': True}]
    ball_name = ball.get('name') or f'{name} ball'
    centre = [at[0] + toward[0] * (0.5 * d + 0.004), axis_y, at[2] + toward[2] * (0.5 * d + 0.004)]
    parts.append({'name': ball_name, 'shape': 'sphere', 'material': material, 'size_m': [d, d, d],
                  'at_m': centre, 'turn_deg': [0, 0, 0], 'fixed': False})
    weight_n = DENSITY_KG_M3.get(material, 7870.0) * math.pi / 6.0 * d ** 3 * 9.81
    area = math.pi * d * d / 4.0
    # The wad: holds the ball until the breech is 0.4 MPa above the air, so
    # the charge burns in a closed breech and THEN throws the ball. A wad that
    # gave at a whisper of pressure let the ball creep out while the powder
    # was still smouldering, and the gas went into a breech growing as fast.
    joints = [{'name': f'{name} wad', 'kind': 'fix', 'a': f'{name} barrel', 'b': ball_name,
               'at_m': [at[0] + toward[0] * 0.002, axis_y, at[2] + toward[2] * 0.002], 'axis': list(toward),
               'holds_shear_n': 0.0, 'holds_tension_n': round(max(10.0 * weight_n, 4.0e5 * area), 1)}]
    # The charge: one small keg that is mostly powder. A charge that is
    # mostly inert only smoulders -- the inert part soaks up the heat the
    # powder makes -- so the keg is as small as the world's cells allow.
    keg = k['_cell']
    parts.append({'name': f'{name} charge', 'shape': 'box', 'material': 'oak', 'size_m': [keg, keg, keg],
                  'at_m': [at[0] - toward[0] * (length + 0.01 + 0.5 * keg), 0.5 * keg,
                           at[2] - toward[2] * (length + 0.01 + 0.5 * keg)], 'turn_deg': [0, 0, 0], 'fixed': True})
    keg_kg = keg ** 3 * DENSITY_KG_M3['oak']
    fraction = powder_g / 1000.0 / keg_kg
    if fraction > 0.9 or fraction < 0.05:
        problems.append(f'{name}: powder_g is {0.05 * keg_kg * 1000:.2f}-{0.9 * keg_kg * 1000:.1f} g: its charge is '
                        f'a {keg * 1000:.0f} mm keg of {keg_kg * 1000:.1f} g, and less than a twentieth of it '
                        'powder only smoulders')
    region = f'{name} breech'
    thermo = k['_thermo']
    # The breech: the gas behind the ball, pushing it along the barrel and the
    # barrel the other way (the recoil). A centimetre of bore behind it. Once
    # the ball has gone the barrel's length it is out of the muzzle and the gas
    # gets out after it. (It starts AT the muzzle, outside the barrel, because
    # a body cannot be inside another here; it is pushed as if from the
    # breech, over the barrel's length.)
    thermo['gas_regions'].append({'name': region, 'contents': {'nitrogen': 1.0}, 'pressure_pa': 101325.0,
                                  'volume_m3': round(area * 0.01, 9), 'piston': ball_name,
                                  'container': f'{name} barrel', 'axis': list(toward), 'area_m2': round(area, 7),
                                  'wall_conductance_w_k': 0.0, 'vent_area_m2': round(area, 7), 'vent_open': False,
                                  'opens_at_stroke_m': length})
    # The charge waits warm, below where it runs away; a primer (or a coil)
    # takes it the rest of the way.
    thermo['contents'].append({'body': f'{name} charge',
                               'contents': {'propellant': round(min(fraction, 0.9), 6),
                                            'ash': round(1.0 - min(fraction, 0.9), 6)},
                               'temperature_k': 500.0, 'environment': region})
    if k.get('fire_at_s') is not None:
        thermo['heaters'].append({'target': f'{name} charge',
                                  'power_w': _num(k, 'primer_w', name, problems, 1500.0, 10.0, 1e5),
                                  'start_s': _num(k, 'fire_at_s', name, problems, 1.0, 0.0, 600.0),
                                  'seconds': 2.0, 'label': f'{name} primer'})
    return parts, joints


def _kit_knife_pendulum(k, problems, name):
    """A blade on a rigid arm hinged to a frame, pulled back and let go: the
    edge leads through the bottom of the swing and cuts what is there, if it
    is going hard enough (docs/cutting-model.md: the work is the material's
    fracture energy plus what a blunt edge crushes, paid bond by bond). The
    blade is a horizontal plate, its edge across the swing on its leading
    side, and the arm holds it at one end, like a scythe's: whatever holds up
    the thing being cut is above it, where an arm over the blade's middle
    would run into it.

    It starts held out level -- pulled back a quarter turn -- and is let go.
    Level, every part of it is square to the world, and the engine builds a
    square part exactly to its faces; a plate tilted at any other angle is
    built of a staircase of the world's cells, and whether its face has matter
    where the edge is declared depends on where it happens to sit (an edge on
    one was refused as off its matter)."""
    arm = _num(k, 'arm_m', name, problems, 0.6, 0.2, 3.0)
    if k.get('pull_back_deg', 90) != 90:
        problems.append(f'{name}: a knife pendulum starts held out level, pull_back_deg 90: a blade tilted at another '
                        'angle is built of a staircase of cells and its edge cannot be laid along it. Use arm_m to '
                        'make it swing harder (it passes the bottom at about the speed of a fall from arm_m)')
    d = _dir(k.get('swing_toward', '+x'), problems, name)
    side = (0.0, 0.0, 1.0) if d[0] else (1.0, 0.0, 0.0)
    cell = k['_cell']
    depth, width, plate = 0.12, 0.2, cell
    aim = k.get('aim_at')
    if aim is not None:
        # Hang it so the edge reaches the named part's near face at the
        # bottom of the swing, at that part's middle height.
        target = (k.get('_known') or {}).get(aim)
        edge_material = k.get('blade_material', 'iron')
        if target is None:
            problems.append(f'{name}: aim_at must name a part declared before this kit ({aim!s} is not one)')
            pivot = [0.0, arm + 0.2, 0.0]
        else:
            if not cuttable(target.get('material', 'oak'), edge_material):
                can = [m for m in HARDNESS_PA if cuttable(m, edge_material)]
                problems.append(f'{name}: aim_at {aim} is {target.get("material", "oak")}, which an {edge_material} edge '
                                f'cannot cut (it cuts {", ".join(can) or "nothing here"}; glass, ceramic, ice and '
                                'concrete crack instead). To cut a weight loose, hang it from a rope (a hanging_weight '
                                'kit with "hang": "rope") and aim at "<that kit\'s name> rope"')
            axes, h = _axes(target), _half(target)
            reach = sum(abs(axes[j][0 if d[0] else 2]) * h[j] for j in range(3))
            centre = target['at_m']
            bottom = [centre[0] - d[0] * (reach + 0.5 * depth + 0.01), centre[1],
                      centre[2] - d[2] * (reach + 0.5 * depth + 0.01)]
            pivot = [bottom[0], bottom[1] + arm + 0.006 + 0.5 * plate, bottom[2]]
    else:
        pivot = _vec(k.get('pivot_m'), 3, name + ' pivot_m', problems)
    if pivot[1] - arm - plate < 0.01:
        problems.append(f'{name}: the blade would hit the ground at the bottom of its swing; raise pivot_m above '
                        f'{arm + plate + 0.01:.2f} m or shorten the arm')
    # The arm at the blade's end on whichever side its swing stays clear of
    # the parts already declared (the one asked for, if arm_side says).
    known = [p for p in (k.get('_known') or {}).values() if p.get('shape') != 'compound']

    def blocked(sign):
        off = [pivot[i] + sign * side[i] * 0.5 * width for i in range(3)]
        for p in known:
            axes_p, h = _axes(p), _half(p)
            ext = [sum(abs(axes_p[j][i]) * h[j] for j in range(3)) for i in range(3)]
            c = p['at_m']
            lateral = 0 if side[0] else 2
            along = 2 if side[0] else 0
            if abs(c[lateral] - off[lateral]) > ext[lateral] + 0.03:
                continue
            if c[1] + ext[1] < pivot[1] - arm or c[1] - ext[1] > pivot[1]:
                continue
            if abs(c[along] - pivot[along]) > ext[along] + arm:
                continue
            return True
        return False

    asked = k.get('arm_side')
    if asked in ('+', '-'):
        arm_sign = 1.0 if asked == '+' else -1.0
    else:
        arm_sign = -1.0 if not blocked(-1.0) else 1.0
    # Held out level on the far side from the swing: radially along -d.
    radius = 0.006 + arm + 0.5 * plate
    hang = [pivot[i] + arm_sign * side[i] * 0.5 * width for i in range(3)]
    arm_c = [hang[i] - d[i] * (0.004 + 0.5 * arm) for i in range(3)]
    blade_c = [pivot[i] - d[i] * radius for i in range(3)]
    # Square to the world: thin along the arm (along d), deep upright, wide
    # across the swing. At the bottom of the swing it lies flat, edge first.
    arm_size = [arm if d[0] else 0.04, 0.04, arm if d[2] else 0.04]
    blade_size = [plate if d[0] else width, depth, width if d[0] else plate]
    # The beam a little above the pin, so the arm's top clears it however
    # far back it is pulled; the hinge is the pin between them.
    beam_t, half_span, clear = 0.06, 0.3 + 0.5 * width, 0.03
    beam_size = [beam_t, beam_t, 2 * half_span + beam_t] if d[0] else [2 * half_span + beam_t, beam_t, beam_t]
    post_h = pivot[1] + clear + beam_t
    frame = k.get('frame_material', 'oak')
    parts = [{'name': name + ' beam', 'shape': 'box', 'material': frame, 'size_m': beam_size,
              'at_m': [pivot[0], pivot[1] + clear + 0.5 * beam_t, pivot[2]], 'turn_deg': [0, 0, 0], 'fixed': True}]
    for tag, sgn in (('A', -1), ('B', 1)):
        parts.append({'name': f'{name} post {tag}', 'shape': 'box', 'material': frame,
                      'size_m': [beam_t, post_h, beam_t],
                      'at_m': [pivot[0] + sgn * side[0] * half_span, 0.5 * post_h, pivot[2] + sgn * side[2] * half_span],
                      'turn_deg': [0, 0, 0], 'fixed': True})
    parts.append({'name': name + ' arm', 'shape': 'box', 'material': 'iron', 'size_m': arm_size,
                  'at_m': arm_c, 'turn_deg': [0, 0, 0], 'fixed': False})
    parts.append({'name': name + ' blade', 'shape': 'box', 'material': k.get('blade_material', 'iron'),
                  'size_m': blade_size, 'at_m': blade_c, 'turn_deg': [0, 0, 0], 'fixed': False})
    # A weight on the arm, near its end: more to carry through the cut. An
    # iron block of whole cells, as near the asked mass as they come.
    heavy = _num(k, 'weight_kg', name, problems, 0.0, 0.0, 60.0)
    if heavy > 0:
        block = max(cell, round((heavy / DENSITY_KG_M3['iron']) ** (1 / 3) / cell) * cell)
        along = min(arm - 0.5 * block, arm - 0.01)
        weight_c = [hang[i] - d[i] * (0.004 + along) for i in range(3)]
        weight_c[1] = pivot[1] + 0.02 + 0.002 + 0.5 * block
        parts.append({'name': name + ' weight', 'shape': 'box', 'material': 'iron', 'size_m': [block] * 3,
                      'at_m': weight_c, 'turn_deg': [0, 0, 0], 'fixed': False})
        extra_joints = [{'name': name + ' weight fixing', 'kind': 'fix', 'a': name + ' arm', 'b': name + ' weight',
                         'at_m': [weight_c[0], pivot[1] + 0.021, weight_c[2]], 'axis': [0, 1, 0],
                         'holds_shear_n': 0.0, 'holds_tension_n': 0.0}]
    else:
        extra_joints = []
    joint_at = [hang[i] - d[i] * (0.005 + arm) for i in range(3)]
    joints = [{'name': name + ' hinge', 'kind': 'hinge', 'a': name + ' beam', 'b': name + ' arm', 'at_m': hang,
               'axis': [side[0], 0.0, side[2]], 'friction_n_m': 0.0},
              {'name': name + ' socket', 'kind': 'fix', 'a': name + ' arm', 'b': name + ' blade',
               'at_m': joint_at, 'axis': [float(d[0]), 0.0, float(d[2])], 'holds_shear_n': 0.0,
               'holds_tension_n': 0.0}] + extra_joints
    # The edge: across the swing, ON the blade's leading face -- its
    # underside as it is let go, its front as it comes through the bottom.
    # An edge set back inside the plate never reaches what the plate's face
    # has already stopped against.
    lead = [blade_c[0], blade_c[1] - 0.5 * depth, blade_c[2]]
    k['_blades'].append({'part': name + ' blade',
                         'heel_m': [lead[i] - side[i] * 0.45 * width for i in range(3)],
                         'tip_m': [lead[i] + side[i] * 0.45 * width for i in range(3)],
                         'facing': [0.0, -1.0, 0.0],
                         'thickness_m': 0.004, 'edge_radius_m': _num(k, 'edge_radius_m', name, problems, 0.0002, 0.00001, 0.005),
                         'bevel_deg': 30.0})
    return parts, joints


KITS = {'ramp': _kit_ramp, 'domino_row': _kit_domino_row, 'lever': _kit_lever,
        'hanging_weight': _kit_hanging_weight, 'plate_on_supports': _kit_plate,
        'pendulum': _kit_pendulum, 'block_tower': _kit_block_tower, 'water_wheel': _kit_water_wheel,
        'steam_engine': _kit_steam_engine, 'cannon': _kit_cannon, 'knife_pendulum': _kit_knife_pendulum}

KIT_HELP = {
    'ramp': 'anchored plank from top_m down to bottom_m (centre of its upper surface at each end, metres), '
            'width_m, thickness_m, material, rails (true), optional ball {material, diameter_m, name} resting at the '
            'top, optional gate: true (needs rails false) -- a bar "<name> gate" across the ramp below the ball on a '
            'slide "<name> gate slide" that moves it toward +z (a ramp along x) or +x (along z) by up to half its '
            'length plus the ball; tie a rope or drum to its OTHER end (at -z or -x, half its length, width_m + '
            '0.3, from its centre) and pull it that way, and the ball rolls',
    'domino_row': 'count boxes standing on the ground from start_m [x, 0, z], direction "+x|-x|+z|-z", spacing_m, '
                  'size_m [thickness, height, width], material',
    'lever': 'pivot block + plank + hinge; pivot_m [x, block height, z], length_m, width_m, thickness_m, limit_deg, '
             'along "x|z", material. Its hinge joint is named "<name> hinge"',
    'hanging_weight': 'post with an oak peg holding a weight: post_m [x, 0, z], drop_m (height of the weight\'s '
                      'underside above the ground), peg_size_m, weight_size_m, weight_material, side "+x|-x|+z|-z", '
                      'holds_shear_n. The weight is named "<name>", the peg "<name> peg". Or "hang": "rope": the weight '
                      'hangs from a rope "<name> rope" (an oak cord, rope_m long, under an arm on the post, at the '
                      'same place the peg would hold it), whose fixing parts in tension (holds_tension_n) when heat '
                      'has weakened it enough; heat the rope with a coil or a torch',
    'plate_on_supports': 'a plate resting on two supports: at_m [x, underside height, z], size_m [x, thickness, z], '
                         'material, span "z|x"',
    'pendulum': 'fixed frame (beam on two posts) with a rope tie to a ball: EITHER aim_at (name of a part declared '
                'earlier; the swing is placed so the ball meets that part at the bottom) OR pivot_m [x, y, z] where '
                'the rope hangs from; rope_m, pull_back_deg (released at rest from this angle), swing_toward '
                '"+x|-x|+z|-z" (the ball is pulled back the other way and swings toward this side through the '
                'bottom), ball {material, diameter_m, name}',
    'block_tower': 'a stack of loose blocks standing on at_m [x, base height, z]: count, size_m [x, y, z], material, '
                   'gap_m. Named "<name> 1" (bottom) up to "<name> <count>"',
    'water_wheel': 'needs ground kind flume. A paddle wheel standing in the trench at at_m [x, _, _] (z is the '
                   'trench line): radius_m, paddles, paddle_width_m, clearance_m above the bed, post_side "+z|-z". One '
                   'rigid body "<name>" on hinge "<name> hinge"; its axle reaches the bank, so a drum rope can wind on '
                   'it at [x, hub height, trench z + (trench width/2 + 0.2) * side]. Optional pour {side "-x"|"+x" '
                   '(which side of the axle the water lands; -x turns it toward +z), offset_m from the axle, height_m '
                   'above the wheel, discharge_l_s (2), speed_m_s, from_s}: a spout "<name> spout" pouring onto the '
                   'paddles; the poured water falls, turns the wheel and runs off down the trench',
    'steam_engine': 'a boiler "<name> boiler" beside a cylinder "<name> cylinder" with a piston "<name> piston" on '
                    'top: at_m [x, base height, z] (the cylinder\'s foot), bore_m (0.24), cylinder_m (0.3 tall), '
                    'water_kg (0.3), boiler_side "+x|-x|+z|-z", heat_w (10000; 0 to heat the boiler only with a '
                    'circuit coil wound on "<name> boiler"), start_s, seconds. The water starts at its boiling point; '
                    'heat boils it, the steam fills the gas "<name> steam" under the piston and lifts it and '
                    'whatever rests on it (about 13 cm/s at 10 kW with the default bore). Use a rose_m station on '
                    'the piston',
    'knife_pendulum': 'a frame with an iron arm "<name> arm" on hinge "<name> hinge" and a blade "<name> blade" '
                      '(a horizontal plate, its sharp edge across the swing on its leading side), pulled back and let '
                      'go from held out level: EITHER aim_at (a part declared earlier; the edge reaches its near face '
                      'at the bottom of the swing, at its middle height) OR pivot_m [x, y, z]; arm_m (0.6; longer swings '
                      'harder), weight_kg (an iron weight on the arm; heavier carries more through the cut), '
                      'edge_radius_m (how sharp: 0.00002 a razor, 0.0002 a working edge, 0.001 blunt; the work per area '
                      'cut is the material\'s fracture energy plus its hardness times twice this), swing_toward '
                      '"+x|-x|+z|-z", blade_material. The engine cuts what '
                      'the edge goes through if the swing pays for it (fracture energy plus crushing, bond by bond); '
                      'an iron edge cuts aluminum, oak and rubber; iron is as hard and glass, ceramic, ice and '
                      'concrete crack instead, so aiming at one is refused. To drop a weight: a hanging_weight kit '
                      'with "hang": "rope" (field hang, value "rope"), and aim_at "<that kit\'s name> rope". Use a '
                      '"cut" station on the rope',
    'cannon': 'an anchored barrel "<name> barrel" with a ball "<name> ball" (or ball.name) at its muzzle on a '
              'cradle, and a powder charge "<name> charge" behind it: at_m [x, height of the bore, z] is the '
              'muzzle, toward "+x|-x|+z|-z" (it fires level that way), length_m, ball {diameter_m (0.06), '
              'material, name}, powder_g (0.2 g throws a 0.06 m iron ball at very roughly 15 m/s; more powder, '
              'faster), fire_at_s (a primer lights it then; leave it out and light it with a circuit coil wound on '
              '"<name> charge", e.g. a switch on a hinge). The gas in "<name> breech" pushes the ball out',
}


# ---- the declaration ---------------------------------------------------------

def compile_spec(spec, lenient=False):
    """Expand kits and check everything the engine will be asked to build.
    Returns the compiled machine; raises MachineRefused with every problem.
    lenient: return what could be compiled, with the problems in it, rather
    than raise -- for showing a piece before it is set down, never for
    building one."""
    problems = []
    if not isinstance(spec, dict):
        raise MachineRefused(['a machine is a JSON object'])
    if spec.get('schema', SCHEMA) != SCHEMA:
        problems.append('schema must be ' + SCHEMA)
    cell = spec.get('cell_m', 0.02)
    if cell not in CELL_CHOICES:
        problems.append('cell_m is 0.02 or 0.04')
        cell = 0.02
    parts, joints, notes, spouts = [], [], [], []
    # Heat, chemistry and gas the kits declare: steam in a cylinder, powder in
    # a breech. Read by the engine's thermochemistry (src/thermo/ThermoJson).
    thermo = {'gas_regions': [], 'contents': [], 'heaters': []}
    blades = []
    ground = compile_ground(spec.get('ground'), problems)
    light_extra = {}   # lamps, sensors and mirrors that kits make (the light section)
    for i, kit in enumerate(spec.get('kits', []) or []):
        if not isinstance(kit, dict) or kit.get('kit') not in KITS:
            problems.append(f'kit {i + 1}: kit is one of {", ".join(KITS)}')
            continue
        name = kit.get('name')
        if not isinstance(name, str) or not name.strip():
            problems.append(f'kit {i + 1} ({kit["kit"]}) needs a name')
            continue
        before = ({key: len(rows) for key, rows in thermo.items()}, len(blades), len(spouts),
                  {key: len(rows) for key, rows in light_extra.items() if isinstance(rows, list)})
        p, j = KITS[kit['kit']](dict(kit, _known={r['name']: r for r in parts if isinstance(r, dict) and 'name' in r},
                                     _ground=ground, _spouts=spouts, _thermo=thermo, _cell=cell,
                                     _blades=blades, _sun=spec.get('sun'), _light=light_extra),
                                problems, name.strip())
        turned = kit.get('turned')
        if turned is not None:
            # Any kit turned as a whole, about a point: everything it made
            # turns with it, and with clear_ground it is then lifted to stand
            # on the ground rather than go into it.
            what = f'kit {name.strip()} turned'
            if not isinstance(turned, dict):
                problems.append(what + ' is {"yaw_deg", "pitch_deg", "roll_deg", "about_m"}')
            else:
                m = heading(*(_num(turned, key, what, problems, 0.0, -360.0, 360.0)
                              for key in ('yaw_deg', 'pitch_deg', 'roll_deg')))
                about = _vec(turned.get('about_m'), 3, what + ' about_m', problems)
                made = (list(j) + [r for key, rows in thermo.items() for r in rows[before[0].get(key, 0):]]
                        + blades[before[1]:] + spouts[before[2]:]
                        + [r for key, rows in light_extra.items() if isinstance(rows, list)
                           for r in rows[before[3].get(key, 0):]])
                turn_rows(m, about, p, made)
                lift = _ground_deficit(p, ground) if turned.get('clear_ground') else 0.0
                if lift > 0.0:
                    shift_rows([0.0, lift + 0.001, 0.0], list(p) + made)
        for row in p:
            row['kit'] = name.strip()
        parts += p
        joints += j
    for row in spec.get('parts', []) or []:
        parts.append(row)
    joints += list(spec.get('joints', []) or [])
    for i, s in enumerate(spec.get('spouts', []) or []):
        if not isinstance(s, dict) or not isinstance(s.get('name'), str) or not s['name'].strip():
            problems.append(f'spout {i + 1} needs a name')
            continue
        spouts.append({'name': s['name'].strip(), 'at_m': s.get('at_m'), 'direction': s.get('direction', [0, -1, 0]),
                       'speed_m_s': s.get('speed_m_s', 1.0), 'discharge_l_s': s.get('discharge_l_s', 1.0),
                       'from_s': s.get('from_s', 0.0), 'until_s': s.get('until_s')})
    # Poured water falls until it reaches the river, so it needs the flume's
    # ground under it to land in.
    checked_spouts = []
    for s in spouts:
        what = 'spout ' + s['name']
        if ground is None:
            problems.append(what + ': poured water needs ground {"kind": "flume", ...} to land in')
            continue
        at = _vec(s['at_m'], 3, what + ' at_m', problems)
        direction = _vec(s['direction'], 3, what + ' direction', problems)
        if math.sqrt(sum(d * d for d in direction)) < 1e-6:
            problems.append(f'{what}: direction must point somewhere')
        x1 = ground['x0_m'] + (ground['nx'] - 1) * ground['cell_m']
        z1 = ground['z0_m'] + (ground['nz'] - 1) * ground['cell_m']
        if not (ground['x0_m'] <= at[0] <= x1 and ground['z0_m'] <= at[2] <= z1):
            problems.append(f'{what}: at_m is off the edge of the ground')
        elif at[1] <= ground_height(ground, at[0], at[2]) + 0.05:
            problems.append(f'{what}: the mouth is at or below the ground')
        row = {'name': s['name'], 'at_m': at, 'direction': direction,
               'speed_m_s': _num(s, 'speed_m_s', what, problems, 1.0, 0, 10),
               'discharge_l_s': _num(s, 'discharge_l_s', what, problems, 1.0, 0.05, 20),
               'from_s': _num(s, 'from_s', what, problems, 0.0, 0, 600)}
        if s.get('until_s') is not None:
            row['until_s'] = _num(s, 'until_s', what, problems, None, row['from_s'] + 0.01, 3600)
        checked_spouts.append(row)
    if len({s['name'] for s in checked_spouts}) != len(checked_spouts):
        problems.append('two spouts share a name')
    if len(checked_spouts) > 8:
        problems.append('at most 8 spouts')
    names = {}
    checked = []
    for i, p in enumerate(parts):
        what = f'part {p.get("name", i + 1)!s}'
        if not isinstance(p, dict):
            problems.append(f'part {i + 1} is not an object')
            continue
        name = p.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 60:
            problems.append(f'part {i + 1} needs a name of 1-60 characters')
            continue
        if name in names:
            problems.append(f'two parts are called {name}')
        shape = p.get('shape', 'box')
        if shape not in SHAPES:
            problems.append(f'{what}: shape is box, sphere or cone')
        material = p.get('material', 'oak')
        if material not in MATERIALS:
            problems.append(f'{what}: material is one of {", ".join(MATERIALS)}')
        if shape == 'compound':
            # One rigid body made of boxes and cylinders, exact rather than
            # built from cells (the engine's precise rigid bodies).
            subs = []
            for k, sub in enumerate(p.get('parts') or []):
                swhat = f'{what} piece {k + 1}'
                if not isinstance(sub, dict) or sub.get('shape', 'box') not in SUB_SHAPES:
                    problems.append(f'{swhat}: shape is box or cylinder')
                    continue
                ssize = _vec(sub.get('size_m'), 3, swhat + ' size_m', problems)
                if min(ssize) <= 0.0 or max(ssize) > 8.0:
                    problems.append(f'{swhat}: sizes between 0 and 8 m')
                subs.append({'shape': sub.get('shape', 'box'), 'size_m': ssize,
                             'at_m': _vec(sub.get('at_m', [0, 0, 0]), 3, swhat + ' at_m', problems),
                             'turn_deg': _vec(sub.get('turn_deg', [0, 0, 0]), 3, swhat + ' turn_deg', problems)})
            if not 1 <= len(subs) <= 64:
                problems.append(f'{what}: a compound has 1 to 64 pieces')
            row = {'name': name, 'shape': 'compound', 'material': material, 'parts': subs,
                   'at_m': _vec(p.get('at_m'), 3, what + ' at_m', problems),
                   'turn_deg': _vec(p.get('turn_deg', [0, 0, 0]), 3, what + ' turn_deg', problems),
                   'fixed': bool(p.get('fixed', False)),
                   'velocity_m_s': _vec(p.get('velocity_m_s', [0, 0, 0]), 3, what + ' velocity_m_s', problems),
                   'kit': p.get('kit')}
            lo = [min(pt[i] for sd in solids_of(row) for pt in footprint_points(sd)) for i in range(3)]
            hi = [max(pt[i] for sd in solids_of(row) for pt in footprint_points(sd)) for i in range(3)]
            row['size_m'] = [round(hi[i] - lo[i], 6) for i in range(3)]
            names[name] = row
            checked.append(row)
            continue
        size = _vec(p.get('size_m'), 3, what + ' size_m', problems)
        if shape == 'sphere':
            size = [size[0]] * 3
        for s in size:
            if s < cell - 1e-9:
                problems.append(f'{what}: every size is at least one cell ({cell} m)')
                break
            if s > 8.0:
                problems.append(f'{what}: no size above 8 m')
                break
        row = {'name': name, 'shape': shape, 'material': material, 'size_m': size,
               'at_m': _vec(p.get('at_m'), 3, what + ' at_m', problems),
               'turn_deg': _vec(p.get('turn_deg', [0, 0, 0]), 3, what + ' turn_deg', problems),
               'fixed': bool(p.get('fixed', False)),
               'velocity_m_s': _vec(p.get('velocity_m_s', [0, 0, 0]), 3, what + ' velocity_m_s', problems),
               'kit': p.get('kit')}
        # The engine builds matter from whole cubic cells, so each side is a
        # whole number of cells. Snap it, keep a part that stood on the ground
        # standing on it, and say so rather than change it silently.
        snapped = [max(cell, round(s / cell) * cell) for s in size]
        if any(abs(a - b) > 1e-9 for a, b in zip(snapped, size)):
            grounded = abs(lowest_point(row)) < 1e-6
            row['size_m'] = [round(s, 6) for s in snapped]
            if grounded:
                row['at_m'][1] -= lowest_point(row)
            notes.append(f'{name}: sized to whole {cell * 1000:.0f} mm cells, '
                         + ' x '.join(f'{s:.3g}' for s in row['size_m']) + ' m')
        if any(abs(v) > 40 for v in row['velocity_m_s']):
            problems.append(f'{what}: starting speed is at most 40 m/s on each axis')
        if abs(row['at_m'][0]) > WORLD_HALF_M or abs(row['at_m'][2]) > WORLD_HALF_M or row['at_m'][1] > WORLD_TOP_M:
            problems.append(f'{what}: keep it within {WORLD_HALF_M:g} m of the middle and below {WORLD_TOP_M:g} m')
        names[name] = row
        checked.append(row)
    if len(checked) > MAX_PARTS:
        problems.append(f'{len(checked)} parts; a machine has at most {MAX_PARTS}')
    cells = sum(math.prod(p['size_m']) * (math.pi / 6 if p['shape'] == 'sphere' else 1)
                for p in checked if p['shape'] != 'compound') / cell ** 3
    if cells > MAX_CELLS:
        problems.append(f'about {cells:,.0f} engine cells at {cell} m; the world budget is {MAX_CELLS:,}')
    for p in checked:
        for solid in solids_of(p):
            pts = footprint_points(solid)
            if solid['shape'] == 'sphere':
                r = 0.5 * solid['size_m'][0]
                pts = [[solid['at_m'][0] + dx, solid['at_m'][1] - r, solid['at_m'][2] + dz]
                       for dx in (-r, 0, r) for dz in (-r, 0, r)]
            low = min(pt[1] for pt in pts)
            under = max(ground_height(ground, pt[0], pt[2]) for pt in pts)
            if low < under - 1e-6:
                problems.append(f'{p["name"]} goes {(under - low) * 1000:.0f} mm into the ground; raise it')
                break
            if ground is not None:
                x1 = ground['x0_m'] + (ground['nx'] - 1) * ground['cell_m']
                z1 = ground['z0_m'] + (ground['nz'] - 1) * ground['cell_m']
                if any(not (ground['x0_m'] <= pt[0] <= x1 and ground['z0_m'] <= pt[2] <= z1) for pt in pts):
                    problems.append(f'{p["name"]} is off the edge of the ground (x {ground["x0_m"]:.2f} to {x1:.2f}, '
                                    f'z {ground["z0_m"]:.2f} to {z1:.2f})')
                    break
    for i, a in enumerate(checked):
        for b in checked[i + 1:]:
            if a['fixed'] and b['fixed']:
                continue
            depth = max(overlap_depth(sa, sb) for sa in solids_of(a) for sb in solids_of(b))
            if depth > OVERLAP_TOLERANCE_M:
                problems.append(f'{a["name"]} and {b["name"]} overlap by about {depth * 1000:.0f} mm; move one apart')
    joint_rows, joint_names = [], set()
    for i, j in enumerate(joints):
        if not isinstance(j, dict):
            problems.append(f'joint {i + 1} is not an object')
            continue
        name = j.get('name') or f'joint {i + 1}'
        what = 'joint ' + name
        if name in joint_names:
            problems.append(f'two joints are called {name}')
        joint_names.add(name)
        kind = j.get('kind')
        if kind not in JOINT_KINDS:
            problems.append(f'{what}: kind is one of {", ".join(JOINT_KINDS)}')
            continue
        if kind == 'gear':
            # Two wheels that turn together at the ratio of their teeth. A gear
            # couples two PINS (hinge joints), not two bodies; teeth in mesh
            # turn the wheels opposite ways, a chain the same way.
            row = {'name': name, 'kind': 'gear', 'a': j.get('a'), 'b': j.get('b'),
                   'teeth_a': int(_num(j, 'teeth_a', what, problems, 12, 3, 500)),
                   'teeth_b': int(_num(j, 'teeth_b', what, problems, 24, 3, 500)),
                   'chain': bool(j.get('chain', False)),
                   'strips_at_n_m': _num(j, 'strips_at_n_m', what, problems, 0.0, 0, 1e6)}
            joint_rows.append(row)
            continue
        if kind == 'pulley':
            # A rope from a on part a, over two fixed points, to b on part b; b
            # moves 1/ratio as far as a and feels ratio times the tension (a
            # block and tackle). The rope pulls and never pushes.
            for end in ('a', 'b'):
                if j.get(end) not in names:
                    problems.append(f'{what}: {end} must name a part ({j.get(end)!s} is not one)')
            row = {'name': name, 'kind': 'pulley', 'a': j.get('a'), 'b': j.get('b'),
                   'at_m': _vec(j.get('at_m'), 3, what + ' at_m', problems),
                   'at_b_m': _vec(j.get('at_b_m'), 3, what + ' at_b_m', problems),
                   'over_a_m': _vec(j.get('over_a_m'), 3, what + ' over_a_m', problems),
                   'over_b_m': _vec(j.get('over_b_m'), 3, what + ' over_b_m', problems),
                   'ratio': _num(j, 'ratio', what, problems, 1.0, 0.1, 20),
                   'length_m': _num(j, 'length_m', what, problems, 0.0, 0, 100)}
            joint_rows.append(row)
            continue
        if kind == 'drum':
            # A rope that winds onto a turning body (the drum, on a pin of its
            # own) from a load: rigid/DrumRope.hpp. It pulls and never pushes.
            for end in ('drum', 'load'):
                if j.get(end) not in names:
                    problems.append(f'{what}: {end} must name a part ({j.get(end)!s} is not one)')
            drum = names.get(j.get('drum'))
            row = {'name': name, 'kind': 'drum', 'drum': j.get('drum'), 'load': j.get('load'),
                   'centre_m': _vec(j.get('centre_m', drum['at_m'] if drum else [0, 0, 0]), 3, what + ' centre_m',
                                    problems),
                   'axis': _vec(j.get('axis', [0, 0, 1]), 3, what + ' axis', problems),
                   'radius_m': _num(j, 'radius_m', what, problems, 0.03, 0.005, 2.0),
                   'load_point_m': _vec(j.get('load_point_m'), 3, what + ' load_point_m', problems),
                   'winds': 1 if j.get('winds', 1) >= 0 else -1,
                   'spare_m': _num(j, 'spare_m', what, problems, 1.0, 0.0, 50.0)}
            row['length_m'] = math.dist(row['centre_m'], row['load_point_m']) + row['spare_m']
            joint_rows.append(row)
            continue
        for end in ('a', 'b'):
            if j.get(end) not in names:
                problems.append(f'{what}: {end} must name a part ({j.get(end)!s} is not one)')
        row = {'name': name, 'kind': kind, 'a': j.get('a'), 'b': j.get('b'),
               'at_m': _vec(j.get('at_m'), 3, what + ' at_m', problems)}
        if kind == 'hinge':
            row['axis'] = _vec(j.get('axis', [0, 0, 1]), 3, what + ' axis', problems)
            if math.hypot(*row['axis']) < 1e-6:
                problems.append(f'{what}: axis cannot be zero')
            row['lower_deg'] = _num(j, 'lower_deg', what, problems, -180, -180, 180)
            row['upper_deg'] = _num(j, 'upper_deg', what, problems, 180, -180, 180)
            row['friction_n_m'] = _num(j, 'friction_n_m', what, problems, 0.0, 0, 1e4)
        elif kind == 'fix':
            row['axis'] = _vec(j.get('axis', [0, 1, 0]), 3, what + ' axis', problems)
            row['holds_shear_n'] = _num(j, 'holds_shear_n', what, problems, 0.0, 0, 1e7)
            row['holds_tension_n'] = _num(j, 'holds_tension_n', what, problems, 0.0, 0, 1e7)
            if j.get('member') is not None:
                if j.get('member') not in (j.get('a'), j.get('b')):
                    problems.append(f'{what}: member is the part the fixing is made of, a or b')
                row['member'] = j.get('member')
        elif kind == 'tie':
            row['at_b_m'] = _vec(j.get('at_b_m'), 3, what + ' at_b_m', problems)
            row['length_m'] = _num(j, 'length_m', what, problems, 0.0, 0, 20)
            row['breaks_at_n'] = _num(j, 'breaks_at_n', what, problems, 0.0, 0, 1e7)
            if j.get('member') is not None:
                row['member'] = j.get('member')
        elif kind == 'slide':
            row['axis'] = _vec(j.get('axis', [0, 0, 1]), 3, what + ' axis', problems)
            if math.hypot(*row['axis']) < 1e-6:
                problems.append(f'{what}: axis cannot be zero')
            row['lower_m'] = _num(j, 'lower_m', what, problems, -1.0, -20, 20)
            row['upper_m'] = _num(j, 'upper_m', what, problems, 1.0, -20, 20)
            row['friction_n'] = _num(j, 'friction_n', what, problems, 0.0, 0, 1e6)
        elif kind == 'spring':
            row['at_b_m'] = _vec(j.get('at_b_m'), 3, what + ' at_b_m', problems)
            row['rest_m'] = _num(j, 'rest_m', what, problems, 0.0, 0, 20)
            row['stiffness_n_m'] = _num(j, 'stiffness_n_m', what, problems, None, 1, 1e7)
            row['damping_n_s_m'] = _num(j, 'damping_n_s_m', what, problems, 0.0, 0, 1e5)
        joint_rows.append(row)
    hinge_names = {j['name'] for j in joint_rows if j['kind'] == 'hinge'}
    for row in joint_rows:
        if row['kind'] == 'gear':
            if row['a'] not in hinge_names or row['b'] not in hinge_names or row['a'] == row['b']:
                problems.append(f'joint {row["name"]}: a gear couples two different hinge joints (a and b name hinges)')
    batteries, battery_names = [], set()
    for b in spec.get('batteries', []) or []:
        name = b.get('name') if isinstance(b, dict) else None
        if not isinstance(name, str) or not name:
            problems.append('a battery needs a name')
            continue
        what = 'battery ' + name
        if b.get('in') not in names:
            problems.append(f'{what}: in must name the part it is in')
        battery_names.add(name)
        batteries.append({'name': name, 'in': b.get('in'),
                          'capacity_j': _num(b, 'capacity_j', what, problems, 2.0e5, 1, 1e9),
                          'voltage_v': _num(b, 'voltage_v', what, problems, 48, 1, 1000),
                          'max_power_w': _num(b, 'max_power_w', what, problems, 0, 0, 1e6)})
        if b.get('charge_j') is not None:
            batteries[-1]['charge_j'] = _num(b, 'charge_j', what, problems, None, 0, batteries[-1]['capacity_j'])
    # The sun: where it stands and how strongly it shines (the engine thins
    # nothing for a fixed sun). Before the light, which shines from it.
    sun = None
    if spec.get('sun') is not None:
        sun_spec = spec['sun'] if isinstance(spec['sun'], dict) else {}
        sun = {'elevation_deg': _num(sun_spec, 'elevation_deg', 'sun', problems, 50, 0.5, 90),
               'azimuth_deg': _num(sun_spec, 'azimuth_deg', 'sun', problems, 180, -360, 360),
               'irradiance_w_m2': _num(sun_spec, 'irradiance_w_m2', 'sun', problems, 1000, 0, 1400)}
    light = compile_light(spec, sun, names, battery_names, problems, light_extra)
    circuits = []
    for c in spec.get('circuits', []) or []:
        name = c.get('name') if isinstance(c, dict) else None
        if not isinstance(name, str) or not name:
            problems.append('a circuit needs a name')
            continue
        what = 'circuit ' + name
        if c.get('battery') not in battery_names:
            problems.append(f'{what}: battery must name a battery')
        row = {'name': name, 'battery': c.get('battery'),
               'source_resistance_ohm': _num(c, 'source_resistance_ohm', what, problems, 0.05, 1e-6, 1e3)}
        # Its loads, in parallel behind the switch: a coil that heats a part,
        # a motor that turns a hinge, or both.
        coil = c.get('coil') if isinstance(c.get('coil'), dict) else None
        if coil is not None:
            if coil.get('heats') not in names:
                problems.append(f'{what}: coil.heats must name the part its coil is wound on')
            row['coil'] = {'heats': coil.get('heats'),
                           'resistance_ohm': _num(coil, 'resistance_ohm', what + ' coil', problems, 1.1, 0.01, 1e6)}
        motor = c.get('motor') if isinstance(c.get('motor'), dict) else None
        if motor is not None:
            if motor.get('hinge') not in hinge_names:
                problems.append(f'{what}: motor.hinge must name the hinge joint the motor turns')
            row['motor'] = {'hinge': motor.get('hinge'),
                            'stall_torque_n_m': _num(motor, 'stall_torque_n_m', what + ' motor', problems, 5.0, 0.01, 1e5),
                            'no_load_rad_s': _num(motor, 'no_load_rad_s', what + ' motor', problems, 10.0, 0.01, 1e4),
                            'brake_torque_n_m': _num(motor, 'brake_torque_n_m', what + ' motor', problems, 0.0, 0, 1e5),
                            'gear_ratio': _num(motor, 'gear_ratio', what + ' motor', problems, 1.0, 0.01, 1e4),
                            # Its throttle while the circuit is closed: 1 full
                            # ahead, -1 full astern.
                            'command': _num(motor, 'command', what + ' motor', problems, 1.0, -1.0, 1.0)}
        if coil is None and motor is None:
            problems.append(f'{what}: a circuit needs a load: a coil, a motor, or both')
        switch = c.get('switch')
        if isinstance(switch, dict) and 'photocell' in switch:   # follows light (the light section)
            row['switch'] = light_switch(switch, what, light, problems)
            switch = None
        if switch is not None:
            if not isinstance(switch, dict) or switch.get('hinge') not in {j['name'] for j in joint_rows if j['kind'] == 'hinge'}:
                problems.append(f'{what}: switch.hinge must name a hinge joint')
            above, below = 'closed_at_or_above_deg' in switch, 'closed_at_or_below_deg' in (switch or {})
            if above == below:
                problems.append(f'{what}: the switch closes at_or_above or at_or_below one hinge reading')
            key = 'closed_at_or_above_deg' if above else 'closed_at_or_below_deg'
            row['switch'] = {'hinge': switch.get('hinge'), key: _num(switch, key, what + ' switch', problems, 0, -179, 179)}
        circuits.append(row)
    # The sun: where it stands and how strongly it shines (the engine thins
    # it through the air by its elevation). Solar panels on parts charge a
    # battery with what falls on them, shadows included.
    solar_panels = []
    for i, sp in enumerate(spec.get('solar_panels', []) or []):
        what = 'solar panel ' + str(sp.get('name', i + 1) if isinstance(sp, dict) else i + 1)
        if not isinstance(sp, dict) or sp.get('part') not in names or sp.get('battery') not in battery_names:
            problems.append(f'{what}: part must name the part it is on and battery the battery it charges')
            continue
        if sun is None:
            problems.append(f'{what}: a solar panel needs a sun')
        normal = _vec(sp.get('normal', [0, 1, 0]), 3, what + ' normal', problems)
        if math.hypot(*normal) < 1e-6:
            problems.append(f'{what}: normal must point somewhere')
        part_row = names[sp['part']]
        # The cell sits on the part's face the normal points out of, so the
        # part itself is never what shades it.
        unit = [v / (math.hypot(*normal) or 1.0) for v in normal]
        if part_row['shape'] == 'sphere':
            reach = 0.5 * part_row['size_m'][0]
        elif part_row['shape'] == 'compound':
            reach = max(max(abs(c) + 0.5 * max(sub['size_m']) for c in sub['at_m']) for sub in part_row['parts'])
        else:
            axes, half = _axes(part_row), _half(part_row)
            reach = sum(abs(sum(axes[j][k] * unit[k] for k in range(3))) * half[j] for j in range(3))
        solar_panels.append({'name': sp.get('name') or f'panel {i + 1}', 'part': sp['part'], 'battery': sp['battery'],
                             'at_m': [part_row['at_m'][k] + unit[k] * reach for k in range(3)], 'normal': normal,
                             'area_m2': _num(sp, 'area_m2', what, problems, 0.25, 0.001, 100),
                             'efficiency': _num(sp, 'efficiency', what, problems, 0.2, 0.01, 1.0)})
    torches = []
    for t in spec.get('torches', []) or []:
        if not isinstance(t, dict) or t.get('target') not in names:
            problems.append('a torch needs a target part')
            continue
        torches.append({'target': t['target'],
                        'power_w': _num(t, 'power_w', 'torch', problems, 2000, 1, 1e5),
                        'seconds': _num(t, 'seconds', 'torch', problems, 60, 0.1, 600)})
    # Edges: on a part made of cells, heel to tip on its matter, facing out
    # of it. The engine checks the rest and refuses an edge in the air.
    checked_blades = []
    for i, b in enumerate(blades + list(spec.get('blades', []) or [])):
        what = f'blade {i + 1}'
        if not isinstance(b, dict) or b.get('part') not in names:
            problems.append(f'{what}: part must name the part the edge is on')
            continue
        if names[b['part']]['shape'] == 'compound':
            problems.append(f'{what}: an edge goes on a part made of cells, not a compound part')
            continue
        heel = _vec(b.get('heel_m'), 3, what + ' heel_m', problems)
        tip = _vec(b.get('tip_m'), 3, what + ' tip_m', problems)
        facing = _vec(b.get('facing'), 3, what + ' facing', problems)
        if 'facing_from' in b:
            facing = [facing[j] - b['facing_from'][j] for j in range(3)]
        if math.dist(heel, tip) < 0.005:
            problems.append(f'{what}: heel_m and tip_m must be at least 5 mm apart')
        if math.hypot(*facing) < 1e-6:
            problems.append(f'{what}: facing must point somewhere')
        checked_blades.append({'part': b['part'], 'heel_m': heel, 'tip_m': tip, 'facing': facing,
                               'thickness_m': _num(b, 'thickness_m', what, problems, 0.004, 0.0005, 0.05),
                               'edge_radius_m': _num(b, 'edge_radius_m', what, problems, 0.0002, 0.00001, 0.005),
                               'bevel_deg': _num(b, 'bevel_deg', what, problems, 30.0, 5.0, 120.0)})
    stations = []
    hinge_names = {j['name'] for j in joint_rows if j['kind'] == 'hinge'}
    slide_names = {j['name'] for j in joint_rows if j['kind'] == 'slide'}
    circuit_names = {c['name'] for c in circuits}
    for s in spec.get('stations', []) or []:
        if not (isinstance(s, dict) and isinstance(s.get('title'), str)):
            continue
        what = 'station ' + s['title']
        rule = s.get('done_when')
        # A station can only be checked off by something that exists; a
        # misspelt name would leave it waiting forever with no reason given.
        if isinstance(rule, dict) and len(rule) == 1:
            kind, arg = next(iter(rule.items()))
            if kind == 'hits':
                ok = isinstance(arg, list) and len(arg) == 2 and all(a in names or a == 'the ground' for a in arg)
                if not ok:
                    problems.append(f'{what}: hits names two parts (or "the ground"); {arg!s} does not')
            elif kind in ('parted', 'broke'):
                if arg not in names:
                    problems.append(f'{what}: {kind} names a part; {arg!s} is not one')
            elif kind == 'hinge_beyond_deg':
                if not isinstance(arg, dict) or arg.get('joint') not in hinge_names or                         not isinstance(arg.get('deg'), (int, float)):
                    problems.append(f'{what}: hinge_beyond_deg needs a hinge joint name and deg')
            elif kind == 'turned_deg':
                if not isinstance(arg, dict) or arg.get('joint') not in hinge_names or \
                        not isinstance(arg.get('deg'), (int, float)):
                    problems.append(f'{what}: turned_deg needs a hinge joint name and deg (total turn, either way)')
            elif kind == 'slid_m':
                if not isinstance(arg, dict) or arg.get('joint') not in slide_names or \
                        not isinstance(arg.get('m'), (int, float)):
                    problems.append(f'{what}: slid_m needs a slide joint name and m')
            elif kind == 'switch_closed':
                if arg not in circuit_names:
                    problems.append(f'{what}: switch_closed names a circuit; {arg!s} is not one')
            elif kind == 'hotter_than_k':
                if not isinstance(arg, dict) or arg.get('part') not in names or not isinstance(arg.get('k'), (int, float)):
                    problems.append(f'{what}: hotter_than_k needs a part and k')
            elif kind == 'cut':
                if arg not in names:
                    problems.append(f'{what}: cut names a part; {arg!s} is not one')
            elif kind == 'in_zone':
                if not isinstance(arg, dict) or arg.get('part') not in names:
                    problems.append(f'{what}: in_zone needs a part, at_m (the zone\'s centre) and size_m')
                else:
                    _vec(arg.get('at_m'), 3, what + ' in_zone at_m', problems)
                    size = _vec(arg.get('size_m'), 3, what + ' in_zone size_m', problems)
                    if min(size) <= 0:
                        problems.append(f'{what}: in_zone size_m must be positive')
            elif kind in ('rose_m', 'moved_m'):
                if not isinstance(arg, dict) or arg.get('part') not in names or \
                        not isinstance(arg.get('m'), (int, float)):
                    problems.append(f'{what}: {kind} needs a part and m (metres from where it started)')
            elif kind == 'dented':
                if arg not in names:
                    problems.append(f'{what}: dented names a part; {arg!s} is not one')
                elif not spec.get('plasticity'):
                    problems.append(f'{what}: a dent needs "plasticity": true (metal and wood then yield and stay bent)')
            elif kind in LIGHT_RULES:
                check_light_rule(kind, arg, light, what, problems)
            else:
                problems.append(f'{what}: done_when is one of hits, hinge_beyond_deg, turned_deg, slid_m, switch_closed, '
                                'hotter_than_k, parted, broke, dented, rose_m, moved_m, cut, in_zone, lit_w, shaded_w')
        elif rule is not None:
            problems.append(f'{what}: done_when is one rule, or null for a station not built yet')
        focus = [f for f in (s.get('focus') or []) if isinstance(f, str) and f in names]
        stations.append({k: s.get(k) for k in ('title', 'shows', 'law', 'maturity', 'done_when')} | {'focus': focus})
    if problems and not lenient:
        raise MachineRefused(problems)
    return ({'problems': problems} if lenient else {}) | {'schema': SCHEMA, 'title': str(spec.get('title', 'Machine'))[:80], 'cell_m': cell, 'ground': ground,
            'parts': checked, 'joints': joint_rows, 'batteries': batteries, 'circuits': circuits,
            'torches': torches, 'spouts': checked_spouts, 'stations': stations, 'cells': round(cells), 'notes': notes,
            'plasticity': bool(spec.get('plasticity', False)), 'sun': sun, 'solar_panels': solar_panels,
            'thermo': {key: rows for key, rows in thermo.items() if rows}, 'blades': checked_blades,
            'light': light}


def scene_of(compiled):
    bodies, precise = [], []
    for p in compiled['parts']:
        if p['shape'] == 'compound':
            precise.append({'name': p['name'], 'material': p['material'], 'position_m': p['at_m'],
                            'orientation_wxyz': quaternion_of_turn(p['turn_deg']),
                            'velocity_m_s': p['velocity_m_s'],
                            'parts': [{'shape': s['shape'], 'dimensions_m': s['size_m'], 'center_local_m': s['at_m'],
                                       'rotation_wxyz': quaternion_of_turn(s['turn_deg'])} for s in p['parts']]})
            continue
        body = {'name': p['name'], 'shape': p['shape'], 'material': p['material'], 'dimensions_m': p['size_m'],
                'center_m': p['at_m'], 'anchored': p['fixed']}
        if any(p['turn_deg']):
            body['rotation_deg'] = p['turn_deg']
        if any(p['velocity_m_s']):
            body['velocity_m_s'] = p['velocity_m_s']
        bodies.append(body)
    scene = {'bodies': bodies}
    if precise:
        scene['precise_rigid_bodies'] = precise
    if compiled.get('ground'):
        scene['terrain'] = ground_scene(compiled['ground'])
    if compiled.get('plasticity'):
        # Metal and wood bonds yield and keep their stretch: dents, measured.
        scene['plasticity'] = True
    if compiled.get('thermo'):
        scene['thermo'] = compiled['thermo']
    if compiled.get('spouts'):
        scene['spouts'] = [{'name': s['name'], 'at_m': s['at_m'], 'direction': s['direction'],
                            'speed_m_s': s['speed_m_s'], 'discharge_m3_s': s['discharge_l_s'] / 1000.0,
                            'from_s': s['from_s'], **({'until_s': s['until_s']} if 'until_s' in s else {})}
                           for s in compiled['spouts']]
    return scene


def default_spec():
    return json.loads((ROOT / 'client/voxel-lab/machine-default.json').read_text(encoding='utf-8'))


# ---- the live world ------------------------------------------------------------

def engine_path(native_hint=None):
    name = 'banjo_live_world_run' + ('.exe' if os.name == 'nt' else '')
    candidates = []
    if os.environ.get('BANJO_LIVE_ENGINE'):
        candidates.append(Path(os.environ['BANJO_LIVE_ENGINE']))
    if native_hint:
        candidates.append(Path(native_hint).with_name(name))
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


class Engine:
    """One banjo_live_world_run process, spoken to a JSON line at a time."""

    def __init__(self, exe, scene, cell, workdir):
        self.scene_path = Path(workdir) / 'scene.json'
        self.scene_path.write_text(json.dumps(scene), encoding='utf-8')
        self.proc = subprocess.Popen([str(exe), '--scene', str(self.scene_path), '--cell', str(cell)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, cwd=str(workdir))
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.first = self._next(60)
        if not self.first.get('ok', False):
            self.close()
            raise ValueError('the engine could not build this world: ' + str(self.first.get('error')))

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _next(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError('the engine did not answer within %g s' % timeout) from None
        if line is None:
            err = self.proc.stderr.read()[-600:] if self.proc.stderr else ''
            raise RuntimeError('the engine stopped' + (': ' + err.strip() if err.strip() else ''))
        return json.loads(line)

    def op(self, timeout=60, **command):
        self.proc.stdin.write(json.dumps(command) + '\n')
        self.proc.stdin.flush()
        reply = self._next(timeout)
        if not reply.get('ok', False):
            raise ValueError(reply.get('error') or 'the engine refused ' + command.get('op', ''))
        return reply

    def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.stdin.write('{"op":"quit"}\n')
                self.proc.stdin.flush()
                self.proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        if self.proc.poll() is None:
            self.proc.kill()


def build_engine(exe, compiled, workdir):
    """Open the world and declare its joints, batteries, circuits and torches,
    in that order, through the engine's own ops. Returns the engine and the
    joint ids by name."""
    engine = Engine(exe, scene_of(compiled), compiled['cell_m'], workdir)
    joint_ids = {}
    try:
        # Gears couple hinges, so they go after every hinge is made.
        for j in sorted(compiled['joints'], key=lambda j: j['kind'] == 'gear'):
            if j['kind'] == 'gear':
                r = engine.op(op='gear', pin_a=joint_ids[j['a']], pin_b=joint_ids[j['b']], teeth_a=j['teeth_a'],
                              teeth_b=j['teeth_b'], chain=j['chain'], strips_at_n_m=j['strips_at_n_m'])
            elif j['kind'] == 'pulley':
                r = engine.op(op='reeve', a=j['a'], b=j['b'], at_a=j['at_m'], at_b=j['at_b_m'], over_a=j['over_a_m'],
                              over_b=j['over_b_m'], ratio=j['ratio'], length_m=j['length_m'])
            elif j['kind'] == 'hinge':
                r = engine.op(op='hinge', a=j['a'], b=j['b'], at=j['at_m'], axis=j['axis'], lower_deg=j['lower_deg'],
                              upper_deg=j['upper_deg'], friction_n_m=j['friction_n_m'])
            elif j['kind'] == 'fix':
                extra = {'member': j['member']} if j.get('member') else {}
                r = engine.op(op='fix', a=j['a'], b=j['b'], at=j['at_m'], axis=j['axis'],
                              holds_shear_n=j['holds_shear_n'], holds_tension_n=j['holds_tension_n'], **extra)
            elif j['kind'] == 'slide':
                r = engine.op(op='slide', a=j['a'], b=j['b'], at=j['at_m'], axis=j['axis'], lower_m=j['lower_m'],
                              upper_m=j['upper_m'], friction_n=j['friction_n'])
            elif j['kind'] == 'drum':
                r = engine.op(op='drum', drum=j['drum'], load=j['load'], centre=j['centre_m'], axis=j['axis'],
                              radius_m=j['radius_m'], load_point=j['load_point_m'], winds=j['winds'],
                              length_m=j['length_m'])
            elif j['kind'] == 'tie':
                extra = {'member': j['member']} if j.get('member') else {}
                r = engine.op(op='tie', a=j['a'], b=j['b'], at_a=j['at_m'], at_b=j['at_b_m'], length_m=j['length_m'],
                              breaks_at_n=j['breaks_at_n'], **extra)
            else:
                r = engine.op(op='spring', a=j['a'], b=j['b'], at_a=j['at_m'], at_b=j['at_b_m'], rest_m=j['rest_m'],
                              stiffness_n_m=j['stiffness_n_m'], damping_n_s_m=j['damping_n_s_m'])
            joint_ids[j['name']] = r['joint']
        for b in compiled.get('blades', []):
            engine.op(op='blade', body=b['part'], heel=b['heel_m'], tip=b['tip_m'], facing=b['facing'],
                      thickness_m=b['thickness_m'], edge_radius_m=b['edge_radius_m'], bevel_deg=b['bevel_deg'])
        store_ids = {}
        for b in compiled['batteries']:
            extra = {'charge_j': b['charge_j']} if 'charge_j' in b else {}
            r = engine.op(op='store', name=b['name'], body=b['in'], capacity_j=b['capacity_j'],
                          voltage_v=b['voltage_v'], max_power_w=b['max_power_w'], **extra)
            store_ids[b['name']] = r['store']
        if compiled.get('sun'):
            engine.op(op='sun', **compiled['sun'])
        for sp in compiled.get('solar_panels', []):
            engine.op(op='solar_panel', name=sp['name'], body=sp['part'], store=store_ids[sp['battery']], at_m=sp['at_m'],
                      normal=sp['normal'], area_m2=sp['area_m2'], efficiency=sp['efficiency'])
        build_light(engine, compiled, store_ids)
        circuit_ids = {}
        for c in compiled['circuits']:
            branches = []
            coil_in = 'plus'
            if 'switch' in c:
                coil_in = 'switched'
                sw = dict(c['switch'])
                if 'photocell' in sw:
                    follows = ('follows_light', light_branch(sw))
                else:
                    follows = ('follows_hinge', {'joint': joint_ids[sw.pop('hinge')], **sw})
                branches.append({'id': 'switch', 'kind': 'switch', 'component': c['name'] + ' switch', 'a': 'plus',
                                 'b': 'switched', 'thermal': 'battery', 'resistance_ohm': 0.001, 'closed': False,
                                 follows[0]: follows[1]})
            if 'coil' in c:
                branches.append({'id': 'coil', 'kind': 'resistor', 'component': c['name'] + ' coil', 'a': coil_in,
                                 'b': 'minus', 'resistance_ohm': c['coil']['resistance_ohm'],
                                 'heats_body': c['coil']['heats']})
            if 'motor' in c:
                m = c['motor']
                motor_id = engine.op(op='motor', joint=joint_ids[m['hinge']], store=store_ids[c['battery']],
                                     stall_torque_n_m=m['stall_torque_n_m'], no_load_rad_s=m['no_load_rad_s'],
                                     brake_torque_n_m=m['brake_torque_n_m'])['motor']
                engine.op(op='drive', motor=motor_id, command=m['command'])
                # Its copper losses warm its own windings, a small lump that
                # loses heat to the air.
                branches.append({'id': 'motor', 'kind': 'motor', 'component': c['name'] + ' motor', 'a': coil_in,
                                 'b': 'minus', 'motor': motor_id, 'gear_ratio': m['gear_ratio'],
                                 'thermal': 'windings'})
            network = {'schema': 'banjo.circuit.v1', 'id': c['name'],
                       'nodes': ['plus', 'minus'] + (['switched'] if 'switch' in c else []),
                       'source': {'store': store_ids[c['battery']], 'positive': 'plus', 'negative': 'minus',
                                  'resistance_ohm': c['source_resistance_ohm'], 'thermal': 'battery'},
                       'thermal_nodes': [{'id': 'battery', 'component': c['battery'], 'capacity_j_k': 2000,
                                          'ambient_w_k': 1}] +
                                        ([{'id': 'windings', 'component': c['name'] + ' motor', 'capacity_j_k': 400,
                                           'ambient_w_k': 2}] if 'motor' in c else []),
                       'branches': branches}
            circuit_ids[c['name']] = engine.op(op='circuit', network=network)['circuit']
        for t in compiled['torches']:
            engine.op(op='heat', target=t['target'], power_w=t['power_w'], seconds=t['seconds'])
        # Start working out a collision that is coming before it arrives (up
        # to 2.5 s ahead), so a break is often ready when the pieces meet.
        engine.op(op='foresee', horizon_s=float(os.environ.get('BANJO_MACHINE_FORESEE', 2.5)))
    except Exception:
        engine.close()
        raise
    return engine, joint_ids, circuit_ids


def family(name):
    """What a piece is a piece of: 'glass plate piece 3 piece 1' -> 'glass plate'."""
    return name.split(' piece ')[0] if isinstance(name, str) else str(name)


def _round(v, places=4):
    return round(v, places) if isinstance(v, float) else v


class MachineSession:
    """A machine running in real time. One engine process; one stepping
    thread; the page asks for what changed since its last frame."""

    def __init__(self, compiled, exe, logs, paced=True):
        self.id = uuid.uuid4().hex
        # Paced: world time follows the wall clock times the speed. Unpaced
        # (a rehearsal): the engine runs as fast as it can; the physics is
        # the same, only nobody is watching it in real time.
        self.paced = paced
        self.compiled = compiled
        self.workdir = Path(tempfile.mkdtemp(prefix='machine-', dir=str(logs)))
        started = time.perf_counter()
        self.engine, self.joint_ids, self.circuit_ids = build_engine(exe, compiled, self.workdir)
        self.build_s = time.perf_counter() - started
        self.lock = threading.Condition()
        self.closed = False
        self.playing = False
        self.speed = 1.0
        self.t = 0.0
        self.seq = 0
        self.bodies = {}
        self.removed = {}
        self.events = []
        self.readouts = {}
        self.error = None
        self.last_used = time.monotonic()
        self.wall_compute_s = 0.0
        self.fracture_s = 0.0
        self.behind_s = 0.0
        self._first_impact = set()
        self._parted = set()
        self._switches = {}
        self._hot = set()
        self._turned = {}
        self.water = None
        self.water_seq = 0
        self.parcels = None
        self._dented = set()
        self.machines = None
        self.joint_kinds = {j['name']: j['kind'] for j in compiled['joints']}
        self.motor_hinges = {c['name']: c['motor']['hinge'] for c in compiled['circuits'] if 'motor' in c}
        # Where each part started, for "rose" and "moved" stations.
        self.starts = {p['name']: list(p['at_m']) for p in compiled['parts']}
        self._pushed = set()
        self.cuts = {}
        self._cut_said = {}
        self._held_since = None
        # The ground as the engine built it, sent to the page once.
        terrain = self.engine.first.get('terrain') or {}
        self.ground_view = ({'grid': terrain.get('grid'), 'heights_b64': terrain.get('heights_b64')}
                            if terrain.get('heights_b64') else None)
        self._ingest(self.engine.first, full=True)
        self._probe()
        self.journal = (self.workdir / 'journal.jsonl').open('w', encoding='utf-8')
        self.journal.write(json.dumps({'machine': compiled, 'joint_ids': self.joint_ids,
                                       'circuit_ids': self.circuit_ids}) + '\n')
        threading.Thread(target=self._run, daemon=True).start()

    # What the engine said, merged into what the page has.
    def _ingest(self, reply, full=False):
        self.seq += 1
        if full or not reply.get('partial', False):
            present = {b['name'] for b in reply.get('bodies', [])}
            for name in list(self.bodies):
                if name not in present:
                    del self.bodies[name]
                    self.removed[name] = self.seq
        for b in reply.get('bodies', []):
            old = self.bodies.get(b['name'])
            row = {k: b[k] for k in ('name', 'shape', 'material', 'dimensions_m', 'position_m', 'orientation_wxyz',
                                     'velocity_m_s', 'anchored', 'color_rgba', 'revision', 'mass_kg', 'dent_mm') if k in b}
            # A dent is permanent set the engine measured, not a redrawn shape:
            # news the first time it is a micrometre deep. At the engine's cell
            # sizes a dent is spread over a cell, so it reads shallower than a
            # real one would (docs/machine-physics-roadmap.md).
            if (b.get('dent_mm') or 0.0) >= 0.001 and family(b['name']) not in self._dented:
                self._dented.add(family(b['name']))
                depth = b['dent_mm']
                said = f'{depth:.1f} mm' if depth >= 0.1 else f'{depth * 1000:.0f} micrometres'
                self._event('dent', f'{b["name"]} dented {said} deep', body=family(b['name']),
                            dent_mm=_round(depth, 5), at_m=b.get('dent_at_m'))
            if 'rigid_parts_local' in b:
                row['rigid_parts_local'] = b['rigid_parts_local']
            elif old and 'rigid_parts_local' in old:
                row['rigid_parts_local'] = old['rigid_parts_local']
            if 'cells_local_m' in b:
                row['cells_local_m'] = b['cells_local_m']
            elif old and 'cells_local_m' in old and old.get('revision') == b.get('revision'):
                row['cells_local_m'] = old['cells_local_m']
            row['seq'] = self.seq
            row['cells_seq'] = self.seq if ('cells_local_m' in b or not old) else old.get('cells_seq', self.seq)
            self.bodies[b['name']] = row
            self.removed.pop(b['name'], None)
        for name in reply.get('gone', []) or []:
            if name in self.bodies:
                del self.bodies[name]
                self.removed[name] = self.seq
        self.t = float(reply.get('t', self.t))
        self._track_moves()
        ingest_light(self, reply)
        if isinstance(reply.get('water'), dict):
            # The engine's own picture of the water: the box of wet columns,
            # each surface in millimetres above base_m.
            self.water = {k: reply['water'].get(k) for k in ('box', 'base_m', 'surface_mm_b64', 'in_m3_s',
                                                             'out_m3_s', 'volume_m3', 'wet_cells', 'residual_m3')}
            self.water_seq = self.seq
        if reply.get('cuts'):
            # Every edge contact since the last reply, as the engine measured it;
            # it sends a finished one once and forgets it, so it is read here.
            for c in reply['cuts']:
                self.cuts[(c.get('blade'), c.get('target'), c.get('at_s'))] = c
            for (blade, target), row in self._cut_summary().items():
                said = self._cut_said.get((blade, target))
                if row['bit'] and said != 'cut' and said != 'through':
                    self._cut_said[(blade, target)] = 'cut'
                    self._event('cut', f'{blade} cuts into {target} {row["how"]} at {row["speed_m_s"]:.1f} m/s',
                                blade=blade, body=target)
                elif not row['bit'] and said is None:
                    self._cut_said[(blade, target)] = 'touch'
                    self._event('contact', f'{blade} meets {target} but does not cut it ({row["kind"]})',
                                blade=blade, body=target)
                if row['through'] and self._cut_said.get((blade, target)) != 'through':
                    self._cut_said[(blade, target)] = 'through'
                    self._event('severed', f'{blade} cut {target} through: {row["area_mm2"]:.0f} mm2 for '
                                f'{row["work_j"]:.2f} J', blade=blade, body=target)
        if isinstance(reply.get('machines'), dict):
            # Batteries, motors and solar panels as the engine last said.
            self.machines = reply['machines']
        if isinstance(reply.get('parcels'), dict):
            # Poured water in the air, every reply: each parcel's centre in
            # millimetres, and the pour's ledger.
            self.parcels = reply['parcels']
        for imp in reply.get('impacts', []) or []:
            # The first contact between two different things is news; pieces
            # of one broken thing knocking about each other is not.
            pair = tuple(sorted((family(imp.get('struck')), family(imp.get('by')))))
            if pair[0] == pair[1] or pair in self._first_impact or imp.get('closing_speed_m_s', 0) < 0.3:
                continue
            self._first_impact.add(pair)
            self._event('impact', f'{imp.get("by")} hits {imp.get("struck")} at {imp["closing_speed_m_s"]:.2f} m/s'
                        + (' (enough to break it)' if imp.get('would_break') else ''),
                        struck=imp.get('struck'), by=imp.get('by'), speed_m_s=_round(imp['closing_speed_m_s']),
                        would_break=bool(imp.get('would_break')))
        mech = reply.get('mechanics') or {}
        for a in mech.get('attachments', []) or []:
            if a.get('attached') is False or a.get('parted_because'):
                key = a.get('id', a.get('joint'))
                if key not in self._parted:
                    self._parted.add(key)
                    self._event('parted', f'{a.get("b")} came off {a.get("a")}: {a.get("parted_because", "")}',
                                a=a.get('a'), b=a.get('b'), why=a.get('parted_because'))

    def _track_closest(self):
        """For each station still waiting on a contact between two parts, the
        closest their centres have come: measured, and what a designer needs
        to know when the contact never happens."""
        closest = self.__dict__.setdefault('closest', {})
        done = getattr(self, '_done_at', {})
        for i, st in enumerate(self.compiled['stations']):
            rule = st.get('done_when')
            if not isinstance(rule, dict) or 'hits' not in rule or i in done:
                continue
            a, b = rule['hits']
            pa = next((x['position_m'] for x in self.bodies.values() if family(x['name']) == a), None)
            pb = next((x['position_m'] for x in self.bodies.values() if family(x['name']) == b), None)
            if pa is None or pb is None:
                continue
            d = math.dist(pa, pb)
            if i not in closest or d < closest[i]['centres_m']:
                closest[i] = {'station': st['title'], 'a': a, 'b': b, 'centres_m': round(d, 3), 'at_s': round(self.t, 3),
                              'a_at_m': [round(v, 3) for v in pa], 'b_at_m': [round(v, 3) for v in pb]}

    def _broke(self, name, answer):
        """News of a break the engine has worked out: how many pieces."""
        if answer.get('outcome') == 'broke' and int(answer.get('pieces') or 0) > 1:
            count = int(answer['pieces'])
            self._event('broke', f'{name} broke into {count} pieces', body=name, pieces=count)

    def _track_moves(self):
        """When each rose_m / moved_m station's part first got that far, read
        on every reply from the engine rather than on the slower probe, so a
        cannon ball that is gone in a twentieth of a second is timed when it
        went."""
        crossed = self.__dict__.setdefault('_crossed', {})
        for i, st in enumerate(self.compiled['stations']):
            rule = st.get('done_when')
            if i in crossed or not isinstance(rule, dict) or not ('rose_m' in rule or 'moved_m' in rule
                                                                  or 'in_zone' in rule):
                continue
            if 'in_zone' in rule:
                # Any piece of the part with its centre inside the box; and
                # how near the box it has come, for a designer (or a search)
                # to know how far off a miss was.
                z = rule['in_zone']
                nearest = self.__dict__.setdefault('zone_nearest', {})
                for b in self.bodies.values():
                    if family(b['name']) != z['part']:
                        continue
                    gap = math.sqrt(sum(max(0.0, abs(b['position_m'][k] - z['at_m'][k]) - 0.5 * z['size_m'][k]) ** 2
                                        for k in range(3)))
                    nearest[i] = min(nearest.get(i, gap), gap)
                    if gap == 0.0:
                        crossed[i] = self.t
                        break
                continue
            r = rule.get('rose_m') or rule.get('moved_m')
            start = self.starts.get(r.get('part'))
            now = next((b['position_m'] for b in self.bodies.values() if family(b['name']) == r.get('part')), None)
            if start and now:
                gone = now[1] - start[1] if 'rose_m' in rule else math.dist(now, start)
                if gone >= r['m']:
                    crossed[i] = self.t

    def _cut_summary(self):
        """Each edge against each part (its pieces counted as it): whether
        it bit, how, what it has cut and what that cost, and whether the part
        is through -- the engine says it came apart, or it is now in pieces."""
        out = {}
        for (blade, target, _), c in self.cuts.items():
            key = (blade, family(target or ''))
            row = out.setdefault(key, {'blade': blade, 'target': key[1], 'bit': False, 'how': '', 'kind': '',
                                       'speed_m_s': 0.0, 'area_mm2': 0.0, 'work_j': 0.0, 'through': False})
            how = {'edge': 'edge first', 'slice': 'slicing', 'press': 'pressing'}.get(c.get('kind'))
            if how and not row['bit']:
                row.update(bit=True, how=how, kind=c.get('kind'), speed_m_s=c.get('speed_m_s', 0.0))
            elif not row['kind']:
                row.update(kind=c.get('kind'), speed_m_s=c.get('speed_m_s', 0.0))
            row['area_mm2'] += c.get('area_mm2', 0.0) or 0.0
            row['work_j'] += c.get('work_j', 0.0) or 0.0
            row['through'] = row['through'] or bool(c.get('separated'))
        for row in out.values():
            if row['bit'] and row['area_mm2'] > 0 and any(b.startswith(row['target'] + ' piece') for b in self.bodies):
                row['through'] = True
        return out

    def _event(self, kind, text, **data):
        self.events.append({'t': round(self.t, 3), 'kind': kind, 'text': text, **data, 'seq': self.seq})
        if len(self.events) > 400:
            self.events = self.events[-400:]

    def _probe(self):
        """Hinge angles, circuits and heat: measured readings for the page."""
        out = {}
        joints = self.engine.op(op='joints').get('joints', [])
        rows = []
        for j in joints:
            name = next((n for n, i in self.joint_ids.items() if i == j['id']), str(j['id']))
            kind = self.joint_kinds.get(name, j['kind'])
            row = {'name': name, 'kind': kind, 'degrees': j.get('degrees'), 'attached': j.get('attached'),
                   'a': j.get('a'), 'b': j.get('b')}
            if kind == 'gear':
                # A gear pair's own reading is no angle anyone set; its two
                # hinges carry the turns.
                row['degrees'] = None
            for key in ('metres', 'tension_n', 'leaves', 'meets', 'wound_m'):
                if key in j:
                    row[key] = j[key]
            if kind == 'hinge' and j.get('degrees') is not None:
                # The reading wraps at +-180; the total turn is unwrapped from
                # readings a tenth of a second apart.
                last, total = self._turned.get(name, (j['degrees'], 0.0))
                step = (j['degrees'] - last + 180.0) % 360.0 - 180.0
                self._turned[name] = (j['degrees'], total + step)
                row['turned_deg'] = round(total + step, 2)
            rows.append(row)
        out['joints'] = rows
        circuits = []
        if self.circuit_ids:
            for c in self.engine.op(op='circuits').get('circuits', []):
                coil = next((b for b in c['branches'] if b['id'] == 'coil'), {})
                motor = next((b for b in c['branches'] if b['id'] == 'motor'), {})
                sw = next((b for b in c['branches'] if b['id'] == 'switch'), None)
                coil_a = coil.get('current_a', 0.0) or 0.0
                current = coil_a + (motor.get('current_a', 0.0) or 0.0)
                row = {'name': c['id'], 'closed': None if sw is None else sw.get('closed'),
                       'current_a': _round(current), 'coil_w': _round(coil_a * coil_a * coil.get('resistance_ohm', 0)),
                       'heats': coil.get('heats_body'), 'drives': self.motor_hinges.get(c['id']),
                       'source_j': _round(c['ledger']['source_j'], 2),
                       'into_body_j': _round(c['ledger'].get('exported_j', 0.0), 2),
                       'electrical_residual_j': c['ledger']['electrical_residual_j']}
                circuits.append(row)
                was = self._switches.get(c['id'])
                if sw is not None and sw.get('closed') and not was:
                    into = ' and '.join(x for x in (row['heats'] and f'the coil on {row["heats"]}',
                                                    row['drives'] and f'the motor on {row["drives"]}') if x)
                    self._event('switch', f'{c["id"]}: switch closed, {current:.1f} A into {into}', circuit=c['id'])
                self._switches[c['id']] = bool(sw and sw.get('closed'))
        out['circuits'] = circuits
        heat = self.engine.op(op='thermo').get('thermo', {})
        hot = []
        for b in heat.get('bodies', []) or []:
            k = b.get('temperature_k', 293.15)
            # Burning is combustion the network measures releasing heat, not
            # merely a body the chemistry is watching.
            release = b.get('heat_release_w', 0.0) or 0.0
            burning = bool(b.get('reacting')) and release > 1.0
            if k > 300.0 or burning:
                hot.append({'name': b['name'], 'temperature_k': _round(k, 1), 'reacting': burning,
                            'heat_release_w': _round(release, 1),
                            'heater_w': _round(b.get('heater_w', 0.0), 1), 'fuel_kg': _round(b.get('fuel_kg', 0.0))})
                if burning and b['name'] not in self._hot:
                    self._hot.add(b['name'])
                    self._event('burning', f'{b["name"]} is burning: {k:.0f} K, its fire giving {release:.0f} W',
                                body=b['name'])
        out['heat'] = sorted(hot, key=lambda r: -r['temperature_k'])[:12]
        gas = []
        for r in heat.get('regions', []) or []:
            gas.append({'name': r['name'], 'pressure_kpa': _round(r.get('pressure_pa', 0.0) / 1000.0, 2),
                        'temperature_k': _round(r.get('temperature_k', 0.0), 1),
                        'stroke_m': _round(r.get('stroke_m', 0.0), 4), 'force_n': _round(r.get('force_n', 0.0), 1),
                        'work_j': _round(r.get('work_to_bodies_j', 0.0), 2), 'piston': r.get('piston'),
                        # Where its column is, for drawing it: from base_m along
                        # the axis for its volume over its area.
                        'base_m': [_round(v, 4) for v in r.get('base_m') or [0, 0, 0]],
                        'axis': r.get('axis'), 'area_m2': r.get('area_m2'),
                        'volume_m3': r.get('volume_m3'), 'vent_open': r.get('vent_open')})
            # News once: the gas has pushed its piston (or ball) along.
            if r.get('piston') and (r.get('stroke_m') or 0.0) > 0.005 and r['name'] not in self._pushed:
                self._pushed.add(r['name'])
                self._event('gas', f'{r["name"]} pushes {r["piston"]}: {r.get("pressure_pa", 0.0) / 1000.0:.0f} kPa',
                            region=r['name'])
        out['gas'] = gas
        if self.cuts:
            out['cuts'] = [dict(row, area_mm2=_round(row['area_mm2'], 1), work_j=_round(row['work_j'], 3))
                           for row in self._cut_summary().values()]
        ledger = heat.get('ledger') or {}
        out['heat_ledger'] = {'heater_in_j': _round(ledger.get('heater_in_j', 0.0), 2),
                              'residual_j': ledger.get('residual_j')}
        if self.machines:
            m = self.machines
            out['machines'] = {
                'batteries': [{'name': s.get('name'), 'charge_j': _round(s.get('charge_j', 0.0), 1),
                               'capacity_j': s.get('capacity_j')} for s in m.get('stores', [])],
                'motors': [{'id': x.get('id'), 'speed_rad_s': _round(x.get('speed_rad_s', 0.0), 3),
                            'torque_n_m': _round(x.get('torque_n_m', 0.0), 3), 'power_w': _round(x.get('power_w', 0.0), 2),
                            'turned_rad': _round(x.get('turned_rad', 0.0), 3)} for x in m.get('motors', [])],
                'solar_panels': [{'name': x.get('name'), 'sunlight_w': _round(x.get('sunlight_w', 0.0), 2),
                                  'power_w': _round(x.get('power_w', 0.0), 2), 'shaded': x.get('shaded'),
                                  'shaded_by': x.get('shaded_by')} for x in m.get('panels', [])]}
        light = probe_light(self)
        if light is not None:
            out['light'] = light
        if self.parcels is not None:
            p = self.parcels
            out['pour'] = {'poured_l': _round(1000 * p.get('poured_m3', 0.0), 2),
                           'landed_l': _round(1000 * p.get('landed_m3', 0.0), 2),
                           'in_air_l': _round(1000 * p.get('in_air_m3', 0.0), 2),
                           'parcels': len(p.get('xyz_mm', [])) // 3, 'residual_m3': p.get('residual_m3')}
        self.readouts = out
        out['stations'] = self._stations(out)

    def _stations(self, out):
        """Each station is done when the engine has MEASURED what it names:
        a contact between two parts, a hinge past a reading, a switch closed,
        a part hotter than a temperature, a fixing parted, a body broken."""
        def same(name, part):
            return isinstance(name, str) and (name == part or name.startswith(part + ' piece'))
        done_at = getattr(self, '_done_at', {})
        self._done_at = done_at
        rows = []
        for i, s in enumerate(self.compiled['stations']):
            rule = s.get('done_when')
            if i not in done_at and isinstance(rule, dict):
                hit = None
                if 'hits' in rule:
                    a, b = rule['hits']
                    hit = next((e['t'] for e in self.events if e['kind'] == 'impact' and
                                ((same(e['by'], a) and same(e['struck'], b)) or (same(e['by'], b) and same(e['struck'], a)))),
                               None)
                elif 'turned_deg' in rule:
                    r = rule['turned_deg']
                    j = next((j for j in out['joints'] if j['name'] == r.get('joint')), None)
                    if j and abs(j.get('turned_deg') or 0.0) >= abs(r['deg']):
                        hit = self.t
                elif 'slid_m' in rule:
                    r = rule['slid_m']
                    j = next((j for j in out['joints'] if j['name'] == r.get('joint')), None)
                    if j and abs(j.get('metres') or 0.0) >= abs(r['m']):
                        hit = self.t
                elif 'hinge_beyond_deg' in rule:
                    r = rule['hinge_beyond_deg']
                    j = next((j for j in out['joints'] if j['name'] == r.get('joint')), None)
                    if j and j.get('degrees') is not None and (
                            j['degrees'] >= r['deg'] if r['deg'] >= 0 else j['degrees'] <= r['deg']):
                        hit = self.t
                elif 'switch_closed' in rule:
                    if self._switches.get(rule['switch_closed']):
                        hit = next((e['t'] for e in self.events if e['kind'] == 'switch' and
                                    e.get('circuit') == rule['switch_closed']), self.t)
                elif 'hotter_than_k' in rule:
                    r = rule['hotter_than_k']
                    if any(h['name'] == r.get('part') and h['temperature_k'] >= r.get('k', 1e9) for h in out['heat']):
                        hit = self.t
                elif any(k in rule for k in LIGHT_RULES):
                    hit = light_station(rule, self)
                elif 'parted' in rule:
                    hit = next((e['t'] for e in self.events if e['kind'] == 'parted' and
                                rule['parted'] in (e.get('a'), e.get('b'))), None)
                elif 'cut' in rule:
                    hit = next((e['t'] for e in self.events if e['kind'] == 'severed' and same(e.get('body'), rule['cut'])),
                               None)
                elif 'rose_m' in rule or 'moved_m' in rule or 'in_zone' in rule:
                    hit = getattr(self, '_crossed', {}).get(i)
                elif 'dented' in rule:
                    hit = next((e['t'] for e in self.events if e['kind'] == 'dent' and same(e.get('body'), rule['dented'])),
                               None)
                elif 'broke' in rule:
                    hit = next((e['t'] for e in self.events if e['kind'] == 'broke' and same(e.get('body'), rule['broke'])),
                               None)
                if hit is not None:
                    done_at[i] = round(hit, 3)
            rows.append({'title': s['title'], 'maturity': s.get('maturity'),
                         'done': i in done_at, 'at_s': done_at.get(i)})
        return rows

    def _run(self):
        clock_start, world_start = time.perf_counter(), self.t
        last_probe = -1.0
        while True:
            with self.lock:
                while not self.closed and not self.playing:
                    self.lock.wait(0.5)
                    clock_start, world_start = time.perf_counter(), self.t
                if self.closed:
                    return
                speed = self.speed
            target = world_start + speed * (time.perf_counter() - clock_start) if self.paced else math.inf
            if self.t > target + 0.002:
                time.sleep(min(0.02, (self.t - target) / speed))
                continue
            if self.t >= MAX_TIME_S:
                with self.lock:
                    self.playing = False
                    self._event('limit', f'stopped at the {MAX_TIME_S:g} s limit for one run')
                continue
            try:
                started = time.perf_counter()
                reply = self.engine.op(op='step', dt=DT_S, n=STEPS_PER_CALL, moved=True)
                # Something is about to break or bend. Played live, its run
                # goes onto the engine's worker and the world keeps going while
                # the pair that met is held still -- but for no more than
                # MAX_HOLD_S of world time: held longer, a held body misses
                # what it should have been doing (a block a cannon ball had
                # knocked at 2.8 m/s sat on its pedestal for seconds while a
                # second run queued). Then the host waits for the answer
                # (`finish`). Unpaced -- a rehearsal, a test, a trial -- it
                # always waits, so the answer is exactly the physics'.
                if reply.get('breakable') and not reply.get('working_on'):
                    name = reply['breakable'][0]
                    f0 = time.perf_counter()
                    fractured = self.engine.op(op='fracture', name=name, wait=not self.paced, timeout=120)
                    self.fracture_s += time.perf_counter() - f0
                    if fractured.get('outcome') != 'working':
                        with self.lock:
                            self._ingest(fractured, full=True)
                            self._broke(name, fractured)
                self.wall_compute_s += time.perf_counter() - started
                with self.lock:
                    self._ingest(reply)
                    if reply.get('finished'):
                        self._broke(reply['finished'], reply)
                    held_since = self._held_since
                    self._held_since = (held_since if held_since is not None else self.t) \
                        if reply.get('working_on') else None
                if self._held_since is not None and self.t - self._held_since > MAX_HOLD_S:
                    f0 = time.perf_counter()
                    finished = self.engine.op(op='finish', timeout=120)
                    self.fracture_s += time.perf_counter() - f0
                    with self.lock:
                        self._ingest(finished, full=True)
                        if finished.get('finished'):
                            self._broke(finished['finished'], finished)
                        self._held_since = None
                with self.lock:
                    self._track_closest()
                    if self.t - last_probe >= 0.1:
                        self._probe()
                        last_probe = self.t
                    self.behind_s = max(0.0, target - self.t) if self.paced else 0.0
                    self.lock.notify_all()
                self.journal.write(json.dumps({'t': self.t, 'events': [e for e in self.events if e['seq'] == self.seq]})
                                   + '\n')
            except Exception as exc:  # the engine refused or stopped: stop, keep the last accepted state
                with self.lock:
                    self.playing = False
                    self.error = str(exc)
                    self._event('stopped', 'the engine stopped: ' + str(exc))
                    self.lock.notify_all()
                return

    def play(self, running, speed=None):
        with self.lock:
            if self.error:
                raise ValueError(self.error)
            if speed is not None:
                if speed not in (0.25, 0.5, 1.0, 2.0, 4.0):
                    raise ValueError('speed is 0.25, 0.5, 1, 2 or 4 times real time')
                self.speed = float(speed)
            self.playing = bool(running)
            self.last_used = time.monotonic()
            self.lock.notify_all()
        return self.frame(0, 0)

    def frame(self, after, wait_ms):
        with self.lock:
            self.last_used = time.monotonic()
            if wait_ms and self.seq <= after and self.playing:
                self.lock.wait(wait_ms / 1000.0)
            bodies = [{k: v for k, v in b.items() if k not in ('seq', 'cells_seq') and
                       (k != 'cells_local_m' or b['cells_seq'] > after)}
                      for b in self.bodies.values() if b['seq'] > after]
            extra = {}
            if self.water is not None and self.water_seq > after:
                extra['water'] = self.water
            if after == 0 and self.ground_view:
                extra['ground'] = self.ground_view
            if self.parcels is not None:
                extra['parcels'] = self.parcels
            return {**extra, 'ok': True, 'session': self.id, 'seq': self.seq, 't': round(self.t, 4),
                    'playing': self.playing, 'speed': self.speed, 'full': after == 0, 'bodies': bodies,
                    'removed': [n for n, s in self.removed.items() if s > after],
                    'events': [e for e in self.events if e['seq'] > after],
                    'readouts': self.readouts, 'error': self.error,
                    'pace': {'compute_s': round(self.wall_compute_s, 3), 'fracture_s': round(self.fracture_s, 3),
                             'behind_s': round(self.behind_s, 3), 'build_s': round(self.build_s, 3)}}

    def close(self):
        with self.lock:
            self.closed = True
            self.lock.notify_all()
        self.engine.close()
        try:
            self.journal.close()
        except OSError:
            pass


def rehearse(compiled, exe, logs, seconds=25.0, wall_limit_s=45.0):
    """Run a machine once, unpaced, and report what the engine measured: which
    stations happened, when, and the events. Nothing is kept and nothing is
    changed; a person still watches the real run afterwards."""
    session = MachineSession(compiled, exe, logs, paced=False)
    started = time.perf_counter()
    try:
        session.play(True)
        with session.lock:
            while True:
                rows = (session.readouts or {}).get('stations', [])
                watched = [r for r, st in zip(rows, compiled['stations']) if st.get('done_when')]
                if (session.error or not session.playing or session.t >= seconds or
                        (watched and all(r['done'] for r in watched)) or time.perf_counter() - started > wall_limit_s):
                    break
                session.lock.wait(0.1)
            done = getattr(session, '_done_at', {})
            return {'world_time_s': round(session.t, 3), 'wall_s': round(time.perf_counter() - started, 2),
                    'error': session.error, 'stations': list(rows),
                    'zone_nearest_m': {compiled['stations'][i]['title']: round(d, 4)
                                       for i, d in sorted(getattr(session, 'zone_nearest', {}).items())},
                    'closest_approach': [c for i, c in sorted(getattr(session, 'closest', {}).items()) if i not in done],
                    'events': [{'t': e['t'], 'text': e['text']} for e in session.events[:80]]}
    finally:
        session.close()


class MachineHost:
    """The server's machines: a few at a time, closed when idle."""

    def __init__(self, exe, logs, limit=4):
        self.exe = exe
        self.logs = Path(logs)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self.sessions = {}
        self.lock = threading.Lock()

    def _sweep(self):
        for key, s in list(self.sessions.items()):
            if time.monotonic() - s.last_used > 600:
                s.close()
                del self.sessions[key]

    def open(self, spec):
        if self.exe is None:
            raise ValueError('The live world engine (banjo_live_world_run) is not built; no substitute is run')
        compiled = compile_spec(spec)
        with self.lock:
            self._sweep()
            if len(self.sessions) >= self.limit:
                oldest = min(self.sessions.values(), key=lambda s: s.last_used)
                oldest.close()
                del self.sessions[oldest.id]
        session = MachineSession(compiled, self.exe, self.logs)
        with self.lock:
            self.sessions[session.id] = session
        reply = session.frame(0, 0)
        reply['machine'] = compiled
        return reply

    def get(self, key):
        with self.lock:
            s = self.sessions.get(key) if isinstance(key, str) else None
        if s is None:
            raise LookupError('That machine is no longer running; build it again')
        return s

    def rehearse(self, compiled):
        if self.exe is None:
            raise ValueError('The live world engine (banjo_live_world_run) is not built; no substitute is run')
        return rehearse(compiled, self.exe, self.logs)

    def close(self, key):
        with self.lock:
            s = self.sessions.pop(key, None) if isinstance(key, str) else None
        if s:
            s.close()
        return {'ok': True, 'closed': bool(s)}

    def close_all(self):
        with self.lock:
            for s in self.sessions.values():
                s.close()
            self.sessions.clear()


# ---- light: the sun, lamps, mirrors and light sensors ------------------------------
#
# docs/optics-checkpoint.md. The engine follows rays of light from the sun and
# from lamps through the world's own shapes: polished metal reflects them, glass
# and ice bend and focus them, and what absorbs them is heated by them. A light
# sensor on a part reads the light reaching its face, and a circuit's switch can
# follow it. Everything here only declares: where the sun stands, which parts
# are mirrors, where lamps and sensors are. What the light does is the engine's.
#
# Kept in one section, with its own kits registered at the end, so that it sits
# beside other kits without touching them.

LIGHT_RULES = ('lit_w', 'shaded_w')
MOST_SUN_RAYS = 8192        # the engine's own limit on the sunlight's rays
METALS = ('aluminum', 'iron')

LIGHT_HELP = '''The machine's "sun" (azimuth_deg round from +z toward +x; a clear day is 1000 W/m2) stands still where it is
put, and "light" traces its rays:
"light": {"sunlight": {"through": [part name, or {"center_m": [..], "size_m": [..]}], "spacing_m": 0.002-0.05}
           (sunlight is traced as rays spacing_m apart only through these boxes, at most 8192 rays: put boxes round
           the lenses, mirrors, sensors and targets that matter, and a fine spacing (2-4 mm) where light is focused),
          "mirrors": [part name] (aluminum or iron parts polished to a mirror: they reflect 0.92 / 0.56 of the light),
          "lamps": [{"name": str, "on": part or null, "at_m": [..], "battery": battery name, "watts": n,
                     "efficacy_lm_w": 120, "axis": [..], "half_angle_deg": 1-180, "rays": 1-1024}],
          "photocells": [{"name": str, "on": part, "at_m": [..] (on the part's face), "normal": [..] (the way the
                          face looks), "area_m2": n}] (a light sensor: it reads the watts of light reaching its face)}
Glass and ice let light through and bend it (a glass ball focuses sunlight about 17 mm beyond its far side, to about
150 times the open sun, but window glass absorbs most of what goes through: a 100 mm glass ball passes about 1.3 W of
the 7.9 W on it); everything else absorbs a share of light and is warmed by it. Heat is spread through the whole of a
part, so focused sunlight cannot set wood alight: to burn a rope with sunlight, let the light work a switch and a coil.
A circuit's switch may follow a sensor: "switch": {"photocell": name, "closed_at_or_above_w": n} (or
"closed_at_or_below_w": n, closed while the beam is broken). Stations: {"lit_w": {"photocell": name, "w": n}} (the
sensor reads at least w), {"shaded_w": {"photocell": name, "w": n}} (it read more than w, then w or less).'''


def _sun_toward(sun):
    el, az = math.radians(sun['elevation_deg']), math.radians(sun['azimuth_deg'])
    return [math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)]


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v] if n > 1e-12 else None


def _part_box(part, margin=0.005):
    """The world box round a part as it is placed, a few millimetres wider."""
    pts = [pt for sd in solids_of(part) for pt in footprint_points(sd)]
    if part['shape'] == 'sphere':
        r = 0.5 * part['size_m'][0]
        pts = [[part['at_m'][i] + (r if (k >> i) & 1 else -r) for i in range(3)] for k in range(8)]
    lo = [min(p[i] for p in pts) - margin for i in range(3)]
    hi = [max(p[i] for p in pts) + margin for i in range(3)]
    return {'center_m': [round(0.5 * (lo[i] + hi[i]), 6) for i in range(3)],
            'size_m': [round(hi[i] - lo[i], 6) for i in range(3)]}


def _sun_rays(boxes, sun, spacing):
    """About how many rays the sunlight asks for as the sun stands: each box's
    shadow across the beam, over the grid's square, with a row round its edge."""
    s = _sun_toward(sun)
    total = 0.0
    for b in boxes:
        x, y, z = b['size_m']
        area = abs(s[0]) * y * z + abs(s[1]) * x * z + abs(s[2]) * x * y
        edge = 2.0 * (x + y + z)
        total += area / spacing ** 2 + edge / spacing
    return int(total)


def compile_light(spec, sun, names, battery_names, problems, extra=None):
    """The machine's light: its sunlight's boxes, its mirrors, lamps and light
    sensors, each checked against the parts and batteries that exist, and the
    machine's sun (compiled with the machine) it shines from. None for a
    machine with no light."""
    light = spec.get('light') or {}
    if not isinstance(light, dict):
        problems.append('light is an object: sunlight, mirrors, lamps, photocells')
        light = {}
    extra = extra or {}
    mirrors = list(light.get('mirrors') or []) + list(extra.get('mirrors') or [])
    lamps_in = list(light.get('lamps') or []) + list(extra.get('lamps') or [])
    cells_in = list(light.get('photocells') or []) + list(extra.get('photocells') or [])
    if sun is None and not light and not any(extra.get(k) for k in ('mirrors', 'lamps', 'photocells')):
        return None
    out = {'sun': sun, 'mirrors': [], 'lamps': [], 'photocells': [], 'sunlight': None,
           'trace_every_steps': int(_num(light, 'trace_every_steps', 'light', problems, 4, 1, 240))}
    for m in mirrors:
        part = names.get(m) if isinstance(m, str) else None
        if part is None:
            problems.append(f'light: mirror {m!s} is not a part')
        elif part['material'] not in METALS:
            problems.append(f'light: mirror {m} is {part["material"]}; only a metal (aluminum or iron) takes a mirror '
                            'polish')
        elif m not in out['mirrors']:
            out['mirrors'].append(m)
    cell_names = set()
    for i, c in enumerate(cells_in):
        what = f'light: photocell {c.get("name", i + 1) if isinstance(c, dict) else i + 1}'
        if not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'].strip():
            problems.append(what + ' needs a name')
            continue
        if c['name'] in cell_names:
            problems.append(f'{what}: two photocells share the name')
        cell_names.add(c['name'])
        if c.get('on') not in names:
            problems.append(f'{what}: on must name the part it is on')
        normal = _vec(c.get('normal'), 3, what + ' normal', problems)
        if _unit(normal) is None:
            problems.append(f'{what}: normal must point somewhere')
        out['photocells'].append({'name': c['name'], 'on': c.get('on'),
                                  'at_m': _vec(c.get('at_m'), 3, what + ' at_m', problems), 'normal': normal,
                                  'area_m2': _num(c, 'area_m2', what, problems, 0.0025, 1e-6, 1.0)})
    lamp_names = set()
    for i, lp in enumerate(lamps_in):
        what = f'light: lamp {lp.get("name", i + 1) if isinstance(lp, dict) else i + 1}'
        if not isinstance(lp, dict) or not isinstance(lp.get('name'), str) or not lp['name'].strip():
            problems.append(what + ' needs a name')
            continue
        if lp['name'] in lamp_names:
            problems.append(f'{what}: two lamps share the name')
        lamp_names.add(lp['name'])
        if lp.get('on') is not None and lp.get('on') not in names:
            problems.append(f'{what}: on names the part it is on, or null for one standing in the air')
        if lp.get('battery') not in battery_names:
            problems.append(f'{what}: battery must name a battery')
        axis = _vec(lp.get('axis'), 3, what + ' axis', problems)
        if _unit(axis) is None:
            problems.append(f'{what}: axis must point somewhere')
        out['lamps'].append({'name': lp['name'], 'on': lp.get('on'), 'battery': lp.get('battery'),
                             'at_m': _vec(lp.get('at_m'), 3, what + ' at_m', problems), 'axis': axis,
                             'watts': _num(lp, 'watts', what, problems, 20.0, 0.1, 5000.0),
                             'efficacy_lm_w': _num(lp, 'efficacy_lm_w', what, problems, 120.0, 1.0, 300.0),
                             'half_angle_deg': _num(lp, 'half_angle_deg', what, problems, 30.0, 0.05, 180.0),
                             'rays': int(_num(lp, 'rays', what, problems, 128, 1, 1024)),
                             'radiant_efficacy_lm_w': _num(lp, 'radiant_efficacy_lm_w', what, problems, 300.0, 1.0,
                                                           683.0),
                             'visible_share': _num(lp, 'visible_share', what, problems, 1.0, 0.0, 1.0)})
    sl = light.get('sunlight')
    if sl is not None:
        if sun is None:
            problems.append('light: sunlight needs a sun ("sun": {"elevation_deg", "azimuth_deg", '
                            '"irradiance_w_m2"})')
        elif not isinstance(sl, dict):
            problems.append('light: sunlight is {"through": [...], "spacing_m": n}')
        else:
            spacing = _num(sl, 'spacing_m', 'light: sunlight', problems, 0.005, 0.002, 0.05)
            boxes = []
            for t in sl.get('through') or []:
                if isinstance(t, str):
                    if t in names:
                        boxes.append(_part_box(names[t]))
                    else:
                        problems.append(f'light: sunlight through {t} -- there is no such part')
                elif isinstance(t, dict):
                    size = _vec(t.get('size_m'), 3, 'light: sunlight box size_m', problems)
                    if min(size) <= 0.0:
                        problems.append('light: a sunlight box has a positive size')
                    boxes.append({'center_m': _vec(t.get('center_m'), 3, 'light: sunlight box center_m', problems),
                                  'size_m': size})
            if not boxes:
                problems.append('light: sunlight goes through at least one part or box (what the light should '
                                'reach: the lenses, mirrors, sensors and targets)')
            elif len(boxes) > 64:
                problems.append('light: sunlight goes through at most 64 parts or boxes')
            elif _sun_rays(boxes, sun, spacing) > MOST_SUN_RAYS:
                problems.append(f'light: sunlight through those boxes at {spacing * 1000:g} mm is about '
                                f'{_sun_rays(boxes, sun, spacing):,} rays; the engine traces at most {MOST_SUN_RAYS:,}: '
                                'give it smaller boxes or a wider spacing')
            out['sunlight'] = {'through': boxes, 'spacing_m': spacing}
    return out


def light_switch(switch, what, light, problems):
    """A circuit's switch that follows a light sensor."""
    cells = {c['name'] for c in (light or {}).get('photocells', [])}
    if switch.get('photocell') not in cells:
        problems.append(f'{what}: switch.photocell must name a photocell')
    above, below = 'closed_at_or_above_w' in switch, 'closed_at_or_below_w' in switch
    if above == below:
        problems.append(f'{what}: the switch closes at_or_above or at_or_below one light reading in watts')
    key = 'closed_at_or_above_w' if above else 'closed_at_or_below_w'
    return {'photocell': switch.get('photocell'), key: _num(switch, key, what + ' switch', problems, 0.5, 0.0, 1e6)}


def check_light_rule(kind, arg, light, what, problems):
    cells = {c['name'] for c in (light or {}).get('photocells', [])}
    if not isinstance(arg, dict) or arg.get('photocell') not in cells or not isinstance(arg.get('w'), (int, float)):
        problems.append(f'{what}: {kind} needs a photocell name and w (watts)')


def build_light(engine, compiled, store_ids):
    """Put the machine's light in the engine, after its sun and before its
    circuits (a switch that follows a sensor needs the sensor there): mirror
    finishes, sensors, lamps with their light, and the sunlight."""
    light = compiled.get('light')
    if not light:
        return {}
    ids = {}
    for m in light['mirrors']:
        engine.op(op='polish', body=m, polished=True)
    for c in light['photocells']:
        ids[c['name']] = engine.op(op='photocell', name=c['name'], body=c['on'], at_m=c['at_m'], normal=c['normal'],
                                   area_m2=c['area_m2'])['photocell']
    for lp in light['lamps']:
        made = engine.op(op='lamp', name=lp['name'], body=lp['on'] or '', store=store_ids[lp['battery']],
                         at_m=lp['at_m'], watts=lp['watts'], efficacy_lm_w=lp['efficacy_lm_w'], on=True)['lamp']
        engine.op(op='lamp_light', name=lp['name'] + ' light', lamp=made, axis=lp['axis'],
                  half_angle_deg=lp['half_angle_deg'], rays=lp['rays'],
                  radiant_efficacy_lm_w=lp['radiant_efficacy_lm_w'], visible_share=lp['visible_share'])
    if light['sunlight']:
        engine.op(op='sunlight', name='sunlight', apertures=light['sunlight']['through'],
                  spacing_m=light['sunlight']['spacing_m'])
    engine.op(op='light_tracing', trace_every_steps=light['trace_every_steps'])
    # Traced once now, so the machine opens with its light where it falls.
    engine.op(op='light_trace')
    return ids


def light_branch(switch):
    """A circuit branch's follows_light, from a compiled light switch."""
    key = 'closed_at_or_above_w' if 'closed_at_or_above_w' in switch else 'closed_at_or_below_w'
    return {'sensor': switch['photocell'], key: switch[key]}


def probe_light(session):
    """What the light is doing, measured, for the page: where its power went,
    what each sensor reads, what it warms, a few rays' paths to draw, and what
    tracing costs. None for a machine with no light."""
    if not session.compiled.get('light'):
        return None
    o = session.engine.op(op='optics').get('optics') or {}
    ingest_light(session, {'optics': o})
    history = session.__dict__.get('_light_history', {})
    cells = []
    for c in o.get('photocells', []):
        peak = max((p for _, p in history.get(c['name'], [])), default=0.0)
        cells.append({'name': c['name'], 'power_w': _round(c.get('power_w', 0.0)), 'peak_w': _round(peak),
                      'at_m': c.get('at_m'), 'normal': c.get('normal'), 'area_m2': c.get('area_m2')})
    lit = sorted(o.get('lit', []), key=lambda b: -b.get('absorbed_w', 0.0))[:8]
    w = o.get('watts') or {}
    return {'sent_w': _round(w.get('sent', 0.0), 3), 'heated_w': _round(w.get('heated', 0.0), 3),
            'residual_w': w.get('residual'), 'joules': o.get('joules'), 'photocells': cells,
            'lit': [{'name': b['body'], 'absorbed_w': _round(b.get('absorbed_w', 0.0), 3)} for b in lit],
            'lights': o.get('lights', []), 'paths': o.get('paths', []), 'cost': o.get('cost')}


def ingest_light(session, reply):
    """What each light sensor read, every time it changed. Every reply of a
    machine with light carries the sensors' last readings (one a trace), so a
    beam broken for a few hundredths of a second, between two of the page's
    readings, is still seen, and seen when it happened."""
    o = reply.get('optics')
    if not isinstance(o, dict):
        return
    history = session.__dict__.setdefault('_light_history', {})
    for c in o.get('photocells', []) or []:
        h = history.setdefault(c['name'], [])
        power = c.get('power_w', 0.0)
        if not h or h[-1][1] != power:
            h.append((round(session.t, 4), power))


def light_station(rule, session):
    """When a light station's rule was first measured as met, or None:
    lit_w when its sensor first read at least w; shaded_w when it first read w
    or less after reading more."""
    kind = 'lit_w' if 'lit_w' in rule else 'shaded_w'
    r = rule[kind]
    history = session.__dict__.get('_light_history', {}).get(r.get('photocell'), [])
    lit = False
    for t, power in history:
        if kind == 'lit_w' and power >= r['w']:
            return t
        if kind == 'shaded_w':
            if power > r['w']:
                lit = True
            elif lit:
                return t
    return None


# -- light kits ------------------------------------------------------------------

def _turn_to_normal(n):
    """turn_deg [x, 0, z] that turns a part's own +y to the unit vector n: the
    engine turns about z first, so +y goes to (-sin z, cos z, 0), and then
    about x, to (-sin z, cos z cos x, cos z sin x)."""
    az = math.degrees(math.asin(max(-1.0, min(1.0, -n[0]))))
    ax = math.degrees(math.atan2(n[2], n[1]))
    return [round(ax, 6), 0.0, round(az, 6)]


def _kit_mirror(k, problems, name):
    """A flat metal plate, fixed and polished, turned so that the sun's light
    from its middle goes to a target: aim_at (a part declared earlier) or
    aim_m (a point). It reflects; where the light lands is the engine's."""
    sun = k.get('_sun')
    if not isinstance(sun, dict):
        problems.append(f'{name}: a mirror kit aims sunlight, so the machine needs a "sun"')
        return [], []
    at = _vec(k.get('at_m'), 3, name + ' at_m', problems)
    w, h = (_vec(k.get('size_m', [0.3, 0.3]), 2, name + ' size_m', problems))
    target = None
    if k.get('aim_at') is not None:
        aimed = (k.get('_known') or {}).get(k['aim_at'])
        if aimed is None:
            problems.append(f'{name}: aim_at must name a part declared before it')
        else:
            target = aimed['at_m']
    elif k.get('aim_m') is not None:
        target = _vec(k.get('aim_m'), 3, name + ' aim_m', problems)
    else:
        problems.append(f'{name}: a mirror needs aim_at (a part) or aim_m (a point)')
    material = k.get('material', 'aluminum')
    if material not in METALS:
        problems.append(f'{name}: a mirror is aluminum or iron')
    if target is None:
        return [], []
    # The machine's sun, with the same defaults its compile gives it.
    to_sun = _sun_toward({'elevation_deg': float(sun.get('elevation_deg', 50.0)),
                          'azimuth_deg': float(sun.get('azimuth_deg', 180.0))})
    to_target = _unit([target[i] - at[i] for i in range(3)])
    n = _unit([to_sun[i] + (to_target or [0, 0, 0])[i] for i in range(3)]) if to_target else None
    if n is None:
        problems.append(f'{name}: the target is where the sun is, or at the mirror itself')
        return [], []
    plate = {'name': name, 'shape': 'box', 'material': material, 'size_m': [w, 0.02, h], 'at_m': at,
             'turn_deg': _turn_to_normal(n), 'fixed': True}
    if k.get('_light') is not None:
        k['_light'].setdefault('mirrors', []).append(name)
    return [plate], []


def _kit_light_gate(k, problems, name):
    """A beam of light across a gap: a lamp on one post shining at a light
    sensor ("<name> eye") on another, at height_m. A thing that passes through
    the beam darkens the sensor; a circuit's switch can follow it."""
    a = _vec(k.get('from_m'), 3, name + ' from_m', problems)
    b = _vec(k.get('to_m'), 3, name + ' to_m', problems)
    height = _num(k, 'height_m', name, problems, 0.3, 0.05, 3.0)
    if k.get('battery') is None:
        problems.append(f'{name}: a light gate needs the battery its lamp runs from')
    along = _unit([b[0] - a[0], 0.0, b[2] - a[2]])
    if along is None:
        problems.append(f'{name}: from_m and to_m must be apart')
        return [], []
    gap = math.hypot(b[0] - a[0], b[2] - a[2])
    half_angle = _num(k, 'half_angle_deg', name, problems, 1.0, 0.1, 10.0)
    post = 0.08
    post_h = height + 0.1
    lamp_at = [a[0] + along[0] * (0.5 * post + 0.005), height, a[2] + along[2] * (0.5 * post + 0.005)]
    eye_at = [b[0] - along[0] * 0.5 * post, height, b[2] - along[2] * 0.5 * post]
    # The sensor is as wide as the beam where it lands, and a little more.
    radius = min(0.035, math.tan(math.radians(half_angle)) * gap + 0.01)
    parts = [{'name': name + ' lamp post', 'shape': 'box', 'material': k.get('post_material', 'concrete'),
              'size_m': [post, post_h, post], 'at_m': [a[0], 0.5 * post_h, a[2]], 'turn_deg': [0, 0, 0], 'fixed': True},
             {'name': name + ' sensor post', 'shape': 'box', 'material': k.get('post_material', 'concrete'),
              'size_m': [post, post_h, post], 'at_m': [b[0], 0.5 * post_h, b[2]], 'turn_deg': [0, 0, 0], 'fixed': True}]
    extra = k['_light'] if k.get('_light') is not None else {}
    extra.setdefault('lamps', []).append({'name': name + ' lamp', 'on': name + ' lamp post', 'at_m': lamp_at,
                                          'battery': k.get('battery'), 'watts': k.get('watts', 10.0),
                                          'efficacy_lm_w': 120.0, 'axis': along, 'half_angle_deg': half_angle,
                                          'rays': 64})
    extra.setdefault('photocells', []).append({'name': name + ' eye', 'on': name + ' sensor post', 'at_m': eye_at,
                                               'normal': [-along[0], 0.0, -along[2]],
                                               'area_m2': round(math.pi * radius * radius, 8)})
    return parts, []


KITS.update({'mirror': _kit_mirror, 'light_gate': _kit_light_gate})
KIT_HELP.update({
    'mirror': 'needs a "sun". A flat polished plate (material aluminum or iron), fixed at at_m [x, y, z] (its middle), '
              'size_m [across, along], turned so that the sun\'s light from its middle reflects toward aim_at (a part '
              'declared earlier) or aim_m [x, y, z]. Several mirrors aimed at one part add their light on it',
    'light_gate': 'a beam of light across a gap at height_m: a lamp on "<name> lamp post" at from_m [x, 0, z] shining '
                  'at a light sensor "<name> eye" on "<name> sensor post" at to_m [x, 0, z]; battery (the lamp\'s '
                  'battery), watts (10: about 4 W of light reach the eye), half_angle_deg (1). A thing in the beam '
                  'darkens the eye: a circuit switch {"photocell": "<name> eye", "closed_at_or_below_w": 1} closes '
                  'then',
})
