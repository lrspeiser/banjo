"""Bounded recipe selection using existing machine heat/input/work laws."""
from copy import deepcopy
import math
import fabrication_room
import machine_routine
import player_world
import workshop_install
from mcp import fabrication


def request(app,owner,body):
    if set(body)-{'session','program','action','recipe','expected_recipe','person'}:
        raise ValueError('Select an existing machine recipe')
    if not getattr(app,'world_id',None) or owner not in player_world.records(app):
        raise ValueError('Join this world before selecting a recipe')
    if type(body.get('program')) is not int:raise ValueError('Select a machine program')
    program=next((p for p in app.live.session.state.get('machines',{}).get('programs',[])
        if p['id']==body['program']),None)
    if program is None:raise ValueError('This machine no longer exists')
    brain=app.brains.of(program['name']);routine=brain.routine
    choices=machine_routine.process_options(app.room.spec,routine)
    if not choices:raise ValueError('This machine has no compatible processing recipes')
    result={'program':program['id'],'recipe':routine.recipe,'power':bool(program.get('power')),
        'choices':deepcopy(choices),'input':routine.intake,'output':routine.output}
    import world_goods
    intake=app.brains.goods.by_name(routine.intake)
    current=app.brains.goods.recipe(routine.recipe)
    if intake is not None and current:
        result['input_readiness']=world_goods.input_readiness(app,owner,intake,set(current['in']))
    if routine.chamber:
        reading=app.live.act({'session':app.live.session.id,'op':'thermo'}).get('thermo') or {}
        region=next((r for r in reading.get('regions',[]) if r.get('name')==routine.chamber),None)
        if region is not None:result['temperature_c']=region['temperature_k']-273.15
    result['element_w']=routine.element_w
    action=body.get('action','view')
    if action=='view':return result
    if action!='select':raise ValueError('Unknown process action')
    recipe=body.get('recipe')
    if recipe not in {r['name'] for r in choices}:raise ValueError('This recipe is incompatible with the machine chamber')
    eyes=(player_world.records(app)[owner].get('pose') or {}).get('eyes_m')
    root=next((b for b in app.live.session.state.get('bodies',[]) if b['name']==program['body']),None)
    if (not isinstance(eyes,list) or len(eyes)!=3 or root is None
            or math.dist(eyes,root['position_m'])>3):raise ValueError('Stand within 3 m of the machine')
    if recipe==routine.recipe:return {**result,'repeated':True}
    if body.get('expected_recipe')!=routine.recipe:raise ValueError('The machine recipe changed; refresh before selecting')
    if program.get('power'):raise ValueError('Stop the machine before changing its recipe')
    if len(routine.frames)>1:raise ValueError('Finish or cancel the machine orders before changing recipe')
    issued=routine.frame.issued or {}
    if issued.get('made') and app.live.session.state['t']<routine.frame.issued_t+issued.get('took_s',0):
        raise ValueError('Wait for the current batch duration before changing recipe')
    saved=workshop_install._snapshot(app.live)
    state=deepcopy(fabrication_room._state(app.room));fabrication.advance(state,saved['t_s'])
    previous=routine.recipe;routine.recipe=recipe
    try:save_error=fabrication_room._persist(app,app.room,saved,state,recover_ack=True)
    except Exception:
        routine.recipe=previous;raise
    brain.changed=True;app.brains._sent.clear()
    if save_error is not None:raise save_error
    selected=app.brains.goods.recipe(recipe)
    if intake is not None and selected:
        result['input_readiness']=world_goods.input_readiness(app,owner,intake,set(selected['in']))
    return {**result,'recipe':recipe,'repeated':False}
