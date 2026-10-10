"""Fitting a foundation pad's footings to the ground where it will stand.

A pad set on a slope as drawn is turned to the slope: its top tilts as much as
the ground does. Its four footings can each be a different length (the
pad's footing_1_m .. footing_4_m), so the same pad can stand level there with
each footing cut to the ground under it. This reads the ground each footing
will bear on, the highest under its foot, and proposes those lengths: a new
version of the design, which the player makes like any other (it costs what
its extra footing costs) and which is installed upright as made
(workshop_install _seat_as_made), not turned to the slope.

The proposal is for one spot and the pad turned as drawn (yaw 0). Nothing is
built or spent here; the stand trial at install still decides.
"""
from copy import deepcopy

# The shortest footing, and the longest the pad allows (FOUNDATION_PARAMETERS).
LEAST_FOOTING_M = .05
MOST_FOOTING_M = 1.5
# Footings past this tall on a slope this steep tend to slide on their bottoms
# (a 0.6 m footing on 22 degrees slid 3 cm in the stand trial): say so.
STEEPEST_FALL_M = .45

CORNERS = ((1, 1), (-1, 1), (1, -1), (-1, -1))   # footing_1 .. footing_4


def footing_middles(parameters, centre_xz):
    """World x/z of each footing's middle for a pad turned as drawn."""
    reach = parameters['width_m'] / 2 - parameters['footing_section_m'] / 2
    deep = parameters['depth_m'] / 2 - parameters['footing_section_m'] / 2
    return [[centre_xz[0] + sx * reach, centre_xz[1] + sz * deep] for sx, sz in CORNERS]


def footing_footprint(parameters, middle):
    """Where the ground is read under one footing's square foot: its middle,
    its four corners and the middles of its four edges."""
    half = parameters['footing_section_m'] / 2
    return [[middle[0] + a * half, middle[1] + b * half] for a in (0, -1, 1) for b in (0, -1, 1)]


def propose(app, candidate, centre_xz):
    """The candidate with footings fitted to the ground at centre_xz."""
    if not isinstance(candidate, dict) or candidate.get('kind') != 'foundation-pad':
        raise ValueError('Only a foundation pad has footings to fit to the ground')
    from mcp import workshop_components
    design, _ = workshop_components.design_from_spec(candidate)
    parameters = dict(design.parameters)
    session = app.live.session
    # A flat foot set down on sloping ground bears on the highest ground under
    # it, not on the ground under its middle: on a slope that is its uphill
    # edge. Read at its middles alone, each footing came out short by however
    # much the ground rises across its own foot there, which differs from foot
    # to foot wherever the slope is not one plane. On the 0.4 m catalog pad,
    # whose footings stand 0.3 m apart, that left a "level" top 1.4 to 1.8
    # degrees out.
    ground = []
    for middle in footing_middles(parameters, centre_xz):
        under = []
        for x, z in footing_footprint(parameters, middle):
            got = (app.live.act({'session': session.id, 'op': 'survey', 'at': [x, z]}) or {}).get('survey') or {}
            if not got.get('on_the_ground'):
                raise ValueError('Part of that spot is off the ground')
            if float((got.get('water') or {}).get('depth_m', 0)) > .005:
                raise ValueError('Part of that spot is under water')
            under.append(float(got['ground_m']))
        ground.append(max(under))
    fall = max(ground) - min(ground)
    if fall > STEEPEST_FALL_M:
        raise ValueError(f'The ground falls {fall:.2f} m under that pad: too steep to stand it on footings. '
                         'Prepare the ground first, or choose flatter ground.')
    lengths = [round(max(ground) - g + LEAST_FOOTING_M, 3) for g in ground]
    if max(lengths) > MOST_FOOTING_M:
        raise ValueError('A footing would be longer than the pad allows')
    fitted = deepcopy(candidate)
    fitted.setdefault('parameters', {}).update(parameters)
    for i, length in enumerate(lengths, 1):
        fitted['parameters'][f'footing_{i}_m'] = length
    workshop_components.design_from_spec(fitted)       # still a valid pad
    return {'schema': 'banjo.construction-fit.v1', 'candidate': fitted,
            'centre_m': [round(v, 4) for v in centre_xz], 'yaw_deg': 0.0,
            'footings_m': lengths, 'fall_m': round(fall, 3),
            'said': (f'Footings cut to the ground: {", ".join(f"{v * 100:.0f}" for v in lengths)} cm. '
                     'Make this version and set it here, turned as drawn, and its top stands level.'),
            'limits': 'For this spot and the pad turned as drawn; the stand trial at install still decides.'}


def request(app, body):
    """POST /api/world/workshop/fit_to_ground: {candidate, position_m, save?,
    label?}. With save, the fitted pad is kept as a new version of the
    player's design (Lab and Recipes show it; Make builds it)."""
    if not isinstance(body, dict) or set(body) - {'candidate', 'position_m', 'save', 'label', 'parent_design_id'}:
        raise ValueError('Fitting takes a candidate pad, a position and whether to save it')
    where = body.get('position_m')
    if (not isinstance(where, list) or len(where) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in where)):
        raise ValueError('position_m is [x, z]')
    answer = propose(app, body.get('candidate'), [float(v) for v in where])
    if body.get('save'):
        import workshop_api_core
        import workshop_library
        import workshop_store
        from mcp import workshop_components
        design, overrides = workshop_components.design_from_spec(answer['candidate'])
        label = str(body.get('label') or f"Foundation pad fitted at {where[0]:.1f}, {where[1]:.1f}")[:120]
        answer['design'] = workshop_store.save(workshop_api_core._store(app), design, label=label,
            parent_design_id=str(body['parent_design_id']) if body.get('parent_design_id') else None)
        answer['library_item'] = workshop_library.save_item(app, item_type='assembly', name=label, payload={
            'schema': 'banjo.workshop-assembly-recipe.v1', 'kind': design.kind, 'design_id': design.design_id,
            'purpose': design.purpose, 'parameters': dict(design.parameters), 'component_overrides': overrides})
    return answer
