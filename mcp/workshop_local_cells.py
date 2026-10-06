"""Explicit component-local material cells with exact clipped box boundaries.

This initial adapter groups each intact component rigidly. Its cells are actual
occupied cuboids, not samples or fracture fragments. Internal deformation,
fracture, refinement/history transfer and wear are unsupported. Existing lattice
sources keep their original solver and resolution.
"""
from copy import deepcopy
from collections import defaultdict
import hashlib
import json
import math
import re

from . import engine_materials, joint_efficiency, workshop_construction, workshop_tools

KEY = '@local_cells'
SCHEMA = 'banjo.workshop-local-cells.v1'
GEOMETRY = 'clipped-box-cells-v1'
MAX_COMPONENT_CELLS = 64
MAX_CELLS = 256
LIMITS = ('Component-local clipped material cells move as rigid constituents. '
          'Finite planar fixings use weaker-material catalog strength; abrupt '
          'failure is uncalibrated. Internal bending, fracture, heat, wear, '
          'adaptive refinement and torsional fixing failure are unsupported.')


def checked(value):
    if (not isinstance(value, dict) or set(value) - {'schema', 'cell_size_m'} or
            value.get('schema', SCHEMA) != SCHEMA):
        raise ValueError('Local cells require a versioned cell_size_m declaration')
    h = value.get('cell_size_m')
    if type(h) not in (float, int) or not math.isfinite(h) or not .002 <= h <= .25:
        raise ValueError('Local cell size must be 2..250 mm')
    return {'schema': SCHEMA, 'cell_size_m': float(h)}


def declaration(design, overrides=None):
    source = overrides if overrides is not None else design.lineage.get('component_overrides', {})
    return checked(source[KEY]) if KEY in (source or {}) else None


def compile_design(design, overrides=None, *, root='local-tool'):
    config = declaration(design, overrides)
    if config is None:
        raise ValueError('Choose local cells explicitly before compiling')
    if not isinstance(root, str) or not re.fullmatch(r'[A-Za-z0-9 _-]{1,64}', root):
        raise ValueError('Local product root must be a short plain identifier')
    from . import workshop_machines, workshop_rigid, workshop_visual
    if workshop_rigid.requested_models(design, overrides) != {'lattice'}:
        raise ValueError('Local cells cannot be combined with another mechanical representation')
    if workshop_machines.of(design):
        raise ValueError('Local cell machines require an additional adapter')
    skins = workshop_visual.skin_overrides(overrides)
    parts = {p.name: p for p in design.parts}
    if not 1 <= len(parts) <= 32:
        raise ValueError('Local products need 1..32 components')
    frame = workshop_tools.frame(design)
    first = frame['grip']['component'] if frame else next(iter(parts))
    names = [first] + sorted(set(parts) - {first})
    mapping = {n: root if i == 0 else f'{root}-g{i}' for i, n in enumerate(names)}
    bounds, bodies, total, materials = {}, [], 0, defaultdict(float)
    for name in names:
        p = parts[name]
        if (p.shape != 'box' or any(abs(v) > 1e-12 for v in p.rotation_deg) or
                skins.get(name, {}).get('physical')):
            raise ValueError(f'{name}: local cells currently require axis-aligned physical boxes')
        if min(p.size_m) < .002 or max(p.size_m) > 6:
            raise ValueError(f'{name}: local component dimensions must be 2..6000 mm')
        lo = [p.center_m[k] - p.size_m[k]/2 for k in range(3)]
        hi = [p.center_m[k] + p.size_m[k]/2 for k in range(3)]
        bounds[name] = (lo, hi)
        # Equal subdivisions avoid a tiny trailing sliver. Nothing is enlarged,
        # snapped to the world origin, or dropped when thinner than h.
        counts = [max(1, math.ceil(v/config['cell_size_m'] - 1e-10)) for v in p.size_m]
        count = math.prod(counts)
        total += count
        if count > MAX_COMPONENT_CELLS or total > MAX_CELLS:
            raise ValueError('Local cells exceed 64 per component or 256 per product; choose a reviewed resolution')
        step = [p.size_m[k]/counts[k] for k in range(3)]
        cells = []
        for x in range(counts[0]):
            for y in range(counts[1]):
                for z in range(counts[2]):
                    grid = (x,y,z)
                    cells.append({'name': f'cell-{len(cells)}', 'dimensions_m': step,
                        'center_local_m': [lo[k] + (grid[k]+.5)*step[k] for k in range(3)]})
        material = engine_materials.scene_name(p.material)
        materials[engine_materials.canonical(material)] += p.volume_m3()*engine_materials.density(material)
        bodies.append({'name': mapping[name], 'material': material,
            'position_m': [0.,0.,0.], 'orientation_wxyz': [1.,0.,0.,0.],
            'parts': cells, 'cell_geometry': GEOMETRY,
            '_centre_m': list(p.center_m), '_components': [name]})
    # Exact nonoverlap and planar mounts, independently of the approximate
    # construction contact tolerance. A declared gap cannot carry a fixing.
    contacts = {}
    for i, a in enumerate(names):
        for b in names[:i]:
            la,ha = bounds[a]; lb,hb = bounds[b]
            spans = [min(ha[k],hb[k])-max(la[k],lb[k]) for k in range(3)]
            if all(v > 1e-10 for v in spans):
                raise ValueError('Local cell components overlap; repair their actual geometry')
            axes = [k for k,v in enumerate(spans) if abs(v) <= 1e-10]
            if len(axes)==1 and all(spans[k]>1e-10 for k in range(3) if k != axes[0]):
                contacts[frozenset((a,b))] = axes[0]
    source_joints = workshop_construction.joints(design)
    graph = {n:set() for n in names}; pins = []; joined=set()
    for j in source_joints:
        pair = frozenset((j['a'],j['b']))
        if j['kind'] != 'fixed' or j.get('open') or pair not in contacts:
            raise ValueError('Every local fixing needs an actual shared planar face; bearings and gaps are unsupported')
        if pair in joined:
            raise ValueError('A local component pair can have only one fixing; duplicate joints cannot multiply strength')
        joined.add(pair)
        a,b = j['a'],j['b']; axis = contacts[pair]; uv=[k for k in range(3) if k != axis]
        la,ha=bounds[a];lb,hb=bounds[b]
        low=[max(la[k],lb[k]) for k in range(3)];high=[min(ha[k],hb[k]) for k in range(3)]
        widths=[high[k]-low[k] for k in uv];area=math.prod(widths)
        strengths=[engine_materials.mechanics(parts[n].material) for n in (a,b)]
        keeps=joint_efficiency.efficiency(j,parts[a],parts[b])
        pins.append({'kind':'fixing','a':mapping[a],'b':mapping[b],
            'at_mm':[500*(low[k]+high[k]) for k in range(3)],
            'axis':[float(k==axis) for k in range(3)],
            'holds_tension_n':min(s['tensile_strength_pa'] for s in strengths)*area*keeps['tension'],
            'holds_shear_n':min(s['shear_strength_pa'] for s in strengths)*area*keeps['shear'],
            'section_u':[float(k==uv[0]) for k in range(3)],
            'section_u_m':widths[0],'section_v_m':widths[1]})
        graph[a].add(b);graph[b].add(a)
    seen=set(); pending=[first]
    while pending:
        n=pending.pop()
        if n not in seen:seen.add(n);pending.extend(graph[n]-seen)
    if seen != set(names):
        raise ValueError('Every local component must be attached by a supported fixing')
    physical={'config':config,'bodies':bodies,'joints':pins,'adapter':SCHEMA}
    return {'schema':SCHEMA,'root':root,'bodies':bodies,'joints':pins,
        'source_joints':source_joints,'component_to_body':mapping,'cells':total,
        'material_mass_kg':dict(materials),'mass_kg':math.fsum(materials.values()),
        'physics_hash':hashlib.sha256(json.dumps(physical,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
        'limitations':[LIMITS]}
