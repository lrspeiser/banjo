"""Read-only material candidates, not loot grants or predicted quantities.

Ground-tool receipts remain authoritative. Rover deposit ledgers are a
separate extraction route and are never substituted for native soil/sand.
"""
from __future__ import annotations


def ground_tool(survey, use, point_length_m=.2):
    surface=survey.get('surface')
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
    if surface=='sand' and 0<sand<point_length_m and float(survey.get('soil_m',0))>0:
        materials.append('soil')
    out.update(materials=materials,state='possible',label='Dig')
    return out
