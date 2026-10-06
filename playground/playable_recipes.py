"""Inorganic game sources, kept separate from historical research prototypes.

Every override changes actual authored material/geometry. Exact rigid plates
do not claim elastic bending, fatigue or real manufacturing chemistry.
"""
from copy import deepcopy
from functools import lru_cache
from mcp import workshop, workshop_components, progression


def recipe(kind, *, design_id=None, parameters=None):
    supplied = dict(parameters or {})
    if kind == 'rover':
        from tools.build_rover_room import inorganic_recipe
        source = inorganic_recipe(design_id=design_id or kind)
        if supplied:
            source['parameters'].update(supplied)
            design=workshop.assemble(kind,design_id=source['design_id'],parameters=source['parameters'])
            source['component_overrides']['@machines']=deepcopy(design.lineage['component_overrides']['@machines'])
        return source
    values = {'material': 'iron'}
    if kind == 'field-pick':
        values.update(length_m=.4, arm_m=.15, section_m=.05)
    elif kind in ('stool', 'table', 'bench', 'chair'):
        values.update(top_thickness_m=.005, leg_section_m=.015,
                          top_profile='square', aprons=0, stretchers=0, splay_deg=0)
        if kind == 'stool': values.update(width_m=.24, depth_m=.24, height_m=.24)
        elif kind in ('table', 'bench'): values.update(width_m=.48, depth_m=.32, height_m=.50)
    elif kind == 'shelf-unit':
        values.update(width_m=.6, depth_m=.25, height_m=.9, shelves=3,
                          top_thickness_m=.005, side_thickness_m=.006)
    elif kind == 'processor':
        values.update(deck_m=.6, top_thickness_m=.01, bin_m=.2)
    elif kind == 'drone':
        values.update(top_thickness_m=.01)
    elif kind == 'cart':
        values.update(top_thickness_m=.01, wheel_width_m=.02)
    elif kind == 'foundation-pad':
        values['material'] = 'concrete'
    values.update(supplied)
    design = workshop.assemble(kind, design_id=design_id or kind, parameters=values)
    overrides = deepcopy(design.lineage.get('component_overrides') or {})
    if kind == 'field-pick':
        # Align both 50 mm members to the native 50 mm cell boundaries rather
        # than doubling their cross-section when the canonical grid samples.
        length,arm,section=(values[key] for key in ('length_m','arm_m','section_m'))
        overrides['haft'] = {'material': 'aluminum', 'center_m': [0., section/2, arm/2+section]}
        overrides['arm'] = {'center_m': [(length-section)/2, section/2, section/2]}
    elif kind == 'solar-array':
        # Preserve the collector's real panel geometry and top contact plane;
        # replace the old solid wood-sized frame/case with thin iron members.
        for part in design.parts:
            x,y,z=part.center_m
            if part.name == 'frame':
                top=y+part.size_m[1]/2
                patch={'size_m':[part.size_m[0],.0035,part.size_m[2]],'center_m':[x,top-.00175,z]}
            elif part.name.startswith('leg-'):
                height=float(design.parameters['frame_height_m'])-.0035
                patch={'size_m':[.01,height,.01],'center_m':[x,height/2,z]}
            elif part.name == 'battery':
                top=float(design.parameters['frame_height_m'])
                patch={'size_m':[.10,.01,.10],'center_m':[x,top+.005,z]}
            else:continue
            overrides.setdefault(part.name,{}).update(patch)
    elif kind in ('stool', 'table', 'bench', 'chair', 'shelf-unit'):
        overrides.update({p.name: {'mechanics': {'model': 'rigid'}} for p in design.parts})
        design.parameters['primary_use'] = {'label': 'Place item', 'steps': [{'do': 'place'}]}
    return {'kind': kind, 'design_id': design.design_id,
            'parameters': dict(design.parameters), 'component_overrides': overrides}


def stone_pick_recipe():
    # The same paid native constituent route, with a genuine aluminum haft.
    from mcp import matter_fabrication
    source = matter_fabrication.stone_pick_recipe()
    source['parameters']['material'] = 'aluminum'
    return source


@lru_cache(maxsize=1)
def registry():
    """A checked game graph; archived wood processes and comparisons remain.

    Matching this compact tool still requires its measured construction and
    native positive use. A label or opening checklist grants no knowledge.
    """
    out = progression.Registry()
    out.material_classes['inorganic-tool'] = ['iron', 'aluminum']
    pick = out.designs['field-pick']
    pick['revision'] = 2
    design, _ = workshop_components.design_from_spec(recipe('field-pick'))
    pick['construction'].update(material_class='inorganic-tool', one_piece=False,
        parts=[{'role': p.role, 'size_m': list(p.size_m)} for p in design.parts])
    out.designs.pop('one-piece-wooden-pick', None)
    out.techniques.pop('rough-shaping-wood', None)
    out.processes = {key: value for key, value in out.processes.items()
                     if key != 'shape-wood-v1'}
    for technique in out.techniques.values():
        earned = technique.get('earned_by') or {}
        if 'any_of' in earned:
            earned['any_of'] = [route for route in earned['any_of']
                if all(need.get('design') in out.designs for need in route.get('all_of', []))]
    # The initial notebook must also be valid in this graph.
    out.start['holds'] = [{'found': 'field-pick'}]
    out.start['first_tools'] = ['field-pick']
    out.start['teaches'] = [t for t in out.start.get('teaches', []) if t in out.techniques]
    out.check()
    return out
