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
JOINT_KINDS = ('hinge', 'fix', 'tie', 'spring', 'slide', 'drum')
DT_S = 1.0 / 240.0
STEPS_PER_CALL = 4
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
    """The engine's turn: about x, then y, then z (TileImpactScene rotateDegrees)."""
    rx, ry, rz = (math.radians(a) for a in turn_deg)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    mx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    my = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    mz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(mz, mul(my, mx))


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
        r = rotation(sub['turn_deg'])
        m = [[sum(outer[i][k] * r[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        # The same matrix as x-y-z turn angles (R = Rz Ry Rx).
        ry = math.asin(max(-1.0, min(1.0, -m[2][0])))
        rx = math.atan2(m[2][1], m[2][2])
        rz = math.atan2(m[1][0], m[0][0])
        out.append({'name': part['name'], 'shape': 'box', 'size_m': size, 'at_m': at,
                    'turn_deg': [math.degrees(rx), math.degrees(ry), math.degrees(rz)]})
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


KITS = {'ramp': _kit_ramp, 'domino_row': _kit_domino_row, 'lever': _kit_lever,
        'hanging_weight': _kit_hanging_weight, 'plate_on_supports': _kit_plate,
        'pendulum': _kit_pendulum, 'block_tower': _kit_block_tower, 'water_wheel': _kit_water_wheel}

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
                      'holds_shear_n. The weight is named "<name>", the peg "<name> peg"',
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
}


# ---- the declaration ---------------------------------------------------------

def compile_spec(spec):
    """Expand kits and check everything the engine will be asked to build.
    Returns the compiled machine; raises MachineRefused with every problem."""
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
    ground = compile_ground(spec.get('ground'), problems)
    for i, kit in enumerate(spec.get('kits', []) or []):
        if not isinstance(kit, dict) or kit.get('kit') not in KITS:
            problems.append(f'kit {i + 1}: kit is one of {", ".join(KITS)}')
            continue
        name = kit.get('name')
        if not isinstance(name, str) or not name.strip():
            problems.append(f'kit {i + 1} ({kit["kit"]}) needs a name')
            continue
        p, j = KITS[kit['kit']](dict(kit, _known={r['name']: r for r in parts if isinstance(r, dict) and 'name' in r},
                                     _ground=ground, _spouts=spouts), problems, name.strip())
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
    circuits = []
    for c in spec.get('circuits', []) or []:
        name = c.get('name') if isinstance(c, dict) else None
        if not isinstance(name, str) or not name:
            problems.append('a circuit needs a name')
            continue
        what = 'circuit ' + name
        if c.get('battery') not in battery_names:
            problems.append(f'{what}: battery must name a battery')
        coil = c.get('coil') if isinstance(c.get('coil'), dict) else None
        if coil is None or coil.get('heats') not in names:
            problems.append(f'{what}: coil.heats must name the part its coil is wound on')
            coil = coil or {}
        row = {'name': name, 'battery': c.get('battery'),
               'coil': {'heats': coil.get('heats'),
                        'resistance_ohm': _num(coil, 'resistance_ohm', what + ' coil', problems, 1.1, 0.01, 1e6)},
               'source_resistance_ohm': _num(c, 'source_resistance_ohm', what, problems, 0.05, 1e-6, 1e3)}
        switch = c.get('switch')
        if switch is not None:
            if not isinstance(switch, dict) or switch.get('hinge') not in {j['name'] for j in joint_rows if j['kind'] == 'hinge'}:
                problems.append(f'{what}: switch.hinge must name a hinge joint')
            above, below = 'closed_at_or_above_deg' in switch, 'closed_at_or_below_deg' in (switch or {})
            if above == below:
                problems.append(f'{what}: the switch closes at_or_above or at_or_below one hinge reading')
            key = 'closed_at_or_above_deg' if above else 'closed_at_or_below_deg'
            row['switch'] = {'hinge': switch.get('hinge'), key: _num(switch, key, what + ' switch', problems, 0, -179, 179)}
        circuits.append(row)
    torches = []
    for t in spec.get('torches', []) or []:
        if not isinstance(t, dict) or t.get('target') not in names:
            problems.append('a torch needs a target part')
            continue
        torches.append({'target': t['target'],
                        'power_w': _num(t, 'power_w', 'torch', problems, 2000, 1, 1e5),
                        'seconds': _num(t, 'seconds', 'torch', problems, 60, 0.1, 600)})
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
            else:
                problems.append(f'{what}: done_when is one of hits, hinge_beyond_deg, turned_deg, slid_m, switch_closed, '
                                'hotter_than_k, parted, broke')
        elif rule is not None:
            problems.append(f'{what}: done_when is one rule, or null for a station not built yet')
        focus = [f for f in (s.get('focus') or []) if isinstance(f, str) and f in names]
        stations.append({k: s.get(k) for k in ('title', 'shows', 'law', 'maturity', 'done_when')} | {'focus': focus})
    if problems:
        raise MachineRefused(problems)
    return {'schema': SCHEMA, 'title': str(spec.get('title', 'Machine'))[:80], 'cell_m': cell, 'ground': ground,
            'parts': checked, 'joints': joint_rows, 'batteries': batteries, 'circuits': circuits,
            'torches': torches, 'spouts': checked_spouts, 'stations': stations, 'cells': round(cells), 'notes': notes}


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
        for j in compiled['joints']:
            if j['kind'] == 'hinge':
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
        store_ids = {}
        for b in compiled['batteries']:
            r = engine.op(op='store', name=b['name'], body=b['in'], capacity_j=b['capacity_j'],
                          voltage_v=b['voltage_v'], max_power_w=b['max_power_w'])
            store_ids[b['name']] = r['store']
        circuit_ids = {}
        for c in compiled['circuits']:
            branches = []
            coil_in = 'plus'
            if 'switch' in c:
                coil_in = 'switched'
                sw = dict(c['switch'])
                follows = {'joint': joint_ids[sw.pop('hinge')]}
                follows.update(sw)
                branches.append({'id': 'switch', 'kind': 'switch', 'component': c['name'] + ' switch', 'a': 'plus',
                                 'b': 'switched', 'thermal': 'battery', 'resistance_ohm': 0.001, 'closed': False,
                                 'follows_hinge': follows})
            branches.append({'id': 'coil', 'kind': 'resistor', 'component': c['name'] + ' coil', 'a': coil_in,
                             'b': 'minus', 'resistance_ohm': c['coil']['resistance_ohm'], 'heats_body': c['coil']['heats']})
            network = {'schema': 'banjo.circuit.v1', 'id': c['name'],
                       'nodes': ['plus', 'minus'] + (['switched'] if 'switch' in c else []),
                       'source': {'store': store_ids[c['battery']], 'positive': 'plus', 'negative': 'minus',
                                  'resistance_ohm': c['source_resistance_ohm'], 'thermal': 'battery'},
                       'thermal_nodes': [{'id': 'battery', 'component': c['battery'], 'capacity_j_k': 2000,
                                          'ambient_w_k': 1}],
                       'branches': branches}
            circuit_ids[c['name']] = engine.op(op='circuit', network=network)['circuit']
        for t in compiled['torches']:
            engine.op(op='heat', target=t['target'], power_w=t['power_w'], seconds=t['seconds'])
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
                                     'velocity_m_s', 'anchored', 'color_rgba', 'revision', 'mass_kg') if k in b}
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
        if isinstance(reply.get('water'), dict):
            # The engine's own picture of the water: the box of wet columns,
            # each surface in millimetres above base_m.
            self.water = {k: reply['water'].get(k) for k in ('box', 'base_m', 'surface_mm_b64', 'in_m3_s',
                                                             'out_m3_s', 'volume_m3', 'wet_cells', 'residual_m3')}
            self.water_seq = self.seq
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
            row = {'name': name, 'kind': j['kind'], 'degrees': j.get('degrees'), 'attached': j.get('attached'),
                   'a': j.get('a'), 'b': j.get('b')}
            for key in ('metres', 'tension_n', 'leaves', 'meets', 'wound_m'):
                if key in j:
                    row[key] = j[key]
            if j['kind'] == 'hinge' and j.get('degrees') is not None:
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
                sw = next((b for b in c['branches'] if b['id'] == 'switch'), None)
                current = coil.get('current_a', 0.0) or 0.0
                row = {'name': c['id'], 'closed': None if sw is None else sw.get('closed'),
                       'current_a': _round(current), 'coil_w': _round(current * current * coil.get('resistance_ohm', 0)),
                       'heats': coil.get('heats_body'), 'source_j': _round(c['ledger']['source_j'], 2),
                       'into_body_j': _round(c['ledger'].get('exported_j', 0.0), 2),
                       'electrical_residual_j': c['ledger']['electrical_residual_j']}
                circuits.append(row)
                was = self._switches.get(c['id'])
                if sw is not None and sw.get('closed') and not was:
                    self._event('switch', f'{c["id"]}: switch closed, {current:.1f} A into the coil on {row["heats"]}',
                                circuit=c['id'])
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
        ledger = heat.get('ledger') or {}
        out['heat_ledger'] = {'heater_in_j': _round(ledger.get('heater_in_j', 0.0), 2),
                              'residual_j': ledger.get('residual_j')}
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
                elif 'parted' in rule:
                    hit = next((e['t'] for e in self.events if e['kind'] == 'parted' and
                                rule['parted'] in (e.get('a'), e.get('b'))), None)
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
                for name in reply.get('breakable', []) or []:
                    f0 = time.perf_counter()
                    fractured = self.engine.op(op='fracture', name=name, timeout=120)
                    self.fracture_s += time.perf_counter() - f0
                    before = {b for b in self.bodies}
                    with self.lock:
                        self._ingest(fractured, full=True)
                        pieces = [b for b in self.bodies if b not in before]
                        if pieces:
                            self._event('broke', f'{name} broke into {len(pieces) + 1} pieces', body=name,
                                        pieces=len(pieces) + 1)
                self.wall_compute_s += time.perf_counter() - started
                with self.lock:
                    self._ingest(reply)
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
