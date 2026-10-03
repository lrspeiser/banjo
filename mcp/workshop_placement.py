"""Bounded installation intent shared by catalog and authored designs.

These are requirements for a proposed site, not a constitutive law or a
certificate of support. Geometry, manufacturing and native checks remain
authoritative. No supplied field grants stock, knowledge or a world position.
"""
from copy import deepcopy
import math

KEY = '@placement'
SCHEMA = 'banjo.construction-contract.v1'


def checked(value):
    if not isinstance(value, dict) or set(value)-{
        'schema', 'support_components', 'upright', 'clearance_m', 'ports', 'skills'}:
        raise ValueError('Unknown construction requirement')
    if value.get('schema', SCHEMA) != SCHEMA:
        raise ValueError('Unknown construction contract version')
    out = {'schema': SCHEMA}
    for key in ('support_components', 'skills'):
        rows = value.get(key, [])
        if (not isinstance(rows, list) or len(rows)>32 or
            any(not isinstance(v,str) or not 1<=len(v)<=120 for v in rows) or
            len(rows)!=len(set(rows))):
            raise ValueError(key+' needs unique bounded names')
        out[key] = list(rows)
    upright = value.get('upright', True)
    if type(upright) is not bool: raise ValueError('upright must be boolean')
    out['upright'] = upright
    clearance = value.get('clearance_m', 0.2)
    if type(clearance) not in (int,float) or not math.isfinite(clearance) or not 0<=clearance<=3:
        raise ValueError('clearance_m must be finite metres between 0 and 3')
    out['clearance_m'] = float(clearance)
    ports = value.get('ports', [])
    if not isinstance(ports,list) or len(ports)>16: raise ValueError('At most 16 construction ports')
    out['ports'] = []
    for port in ports:
        if (not isinstance(port,dict) or set(port)!={'component','kind'} or
            port['kind'] not in ('input','output','power','access') or
            not isinstance(port['component'],str) or not 1<=len(port['component'])<=120):
            raise ValueError('A construction port needs a component and supported kind')
        if port in out['ports']: raise ValueError('Duplicate construction port')
        out['ports'].append(deepcopy(port))
    return out


def for_design(design):
    declared = (design.lineage.get('component_overrides') or {}).get(KEY)
    parts = {p.name:p for p in design.parts}
    measured = design.measure()
    defaults = {'support_components':measured['standing_on'], 'upright':True}
    from mcp import workshop_machines
    ports=[]
    for program in workshop_machines.of(design).get('programs',[]):
        routine=program.get('routine') or {}
        for kind in ('input','output'):
            component=routine.get('intake' if kind=='input' else 'output')
            port={'kind':kind,'component':component}
            if component in parts and port not in ports:ports.append(port)
    defaults['ports']=ports
    intent = checked(declared if declared is not None else defaults)
    named = intent['support_components']+[p['component'] for p in intent['ports']]
    if any(name not in parts for name in named):
        raise ValueError('Construction requirements name a missing component')
    corners = [c for name in intent['support_components'] for c in parts[name].corners_m()]
    intent['support_bounds_m'] = ([[min(c[a] for c in corners),max(c[a] for c in corners)]
                                   for a in range(3)] if corners else None)
    # Preview take IDs differ between Catalog and Lab even when the authored
    # geometry is identical. Requirements describe the design, not that take.
    intent['kind'] = design.kind
    from mcp import workshop_construction
    intent['connections'] = deepcopy(workshop_construction.adopted(design).get('joints',[]))
    intent['supplies'] = {'source':'paid manufacturing quote', 'reserved':False}
    intent['placement_checked'] = False
    intent['limits'] = 'Installation intent. Native placement, settling and operation still require checks.'
    return intent
