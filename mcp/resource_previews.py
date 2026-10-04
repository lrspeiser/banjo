"""Read-only material candidates, not loot grants or predicted quantities.

Ground-tool receipts remain authoritative. Rover deposit ledgers are a
separate extraction route and are never substituted for native soil/sand.
"""
from __future__ import annotations


def ground_tool(survey, use, point_length_m=.2):
    surface=survey.get('surface')
    # The coarse contact classification treats a <2 cm sand film as soil.
    # The visible top run still contains sand and native stripping removes it.
    # Prefer the surveyed run identity, as terrain rendering does.
    runs=survey.get('runs') or []
    if runs:surface=runs[-1]['material']
    water=survey.get('water') or {}
    wet=float(water.get('depth_m',0) if isinstance(water,dict) else water)
    out={'method':'ground-tool','materials':[],'state':'unavailable','label':'No loose materials'}
    if not survey.get('on_the_ground'):return out
    if wet>.005:
        out['label']='Wet ground · unsupported';return out
    if use.get('lever') is None:
        out['label']='No loosening motion';return out
    if surface not in ('sand','soil','loose soil'):
        out['label']='No soil / sand here';return out
    materials=['sand' if surface=='sand' else 'soil']
    # Native excavation can cross a thin sand layer. A candidate is not a
    # promise that the bounded hand will reach that layer or break it loose.
    sand=float(survey.get('sand_m',0))
    loose=float(survey.get('loose_soil_m',0))
    if surface in ('sand','loose soil') and sand>0 and 'sand' not in materials:
        materials.append('sand')
    if surface=='sand' and loose>0:
        materials.append('soil')
    if surface in ('sand','loose soil') and 0<sand+loose<point_length_m and float(survey.get('soil_m',0))>0 and 'soil' not in materials:
        materials.append('soil')
    out.update(materials=materials,state='possible',label='Dig')
    return out


def tool_feedback(result):
    """Present the readiness used by run(); candidates never grant materials.

    Built-in and authored tools, chat and the panel share this decision.
    Native contact may be enabled without a supported gathering yield.
    """
    gather = result.get('gather') or {}
    ring = result.get('ring') or {}
    target = result.get('target') or {}
    out = {'tool': result.get('object'), 'ready': False, 'state': 'blocked',
           'action': 'Unavailable', 'screen': None, 'materials': [],
           'reason': result.get('reason')}
    if not result.get('object'):
        out.update(state='tool-needed', action='Hold a digging tool', screen='inventory')
    elif target.get('kind') == 'object':
        out.update(ready=bool(result.get('enabled')),
                   state='ready' if result.get('enabled') else 'blocked',
                   action=result.get('label', 'Strike') if result.get('enabled') else 'Cannot strike')
    elif (result.get('carried') or {}).get('available_kg', 1) <= .0005:
        out.update(action='Free load space', screen='inventory')
    elif ring.get('state') == 'far':
        out['action'] = 'Move closer'
    elif ring.get('state') == 'near':
        out['action'] = 'Step back'
    elif gather.get('label') == 'No attached tool point':
        out.update(action='Inspect tool', screen='inventory')
    elif not target:
        out['action'] = 'Aim at ground'
    elif not result.get('enabled'):
        pass
    elif gather.get('state') == 'possible' and gather.get('materials'):
        out.update(ready=True, state='ready', action=result.get('label') or 'Dig',
                   materials=list(gather['materials']), reason=None)
    else:
        out.update(state='no-yield', action='Find loose ground',
                   reason=gather.get('label') or out['reason'])
    return out
