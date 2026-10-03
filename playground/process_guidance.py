"""Read-only paths to a positive supported batch using current private supplies.

Recipe-ledger conversions and reported avatar views are not chemistry or body
physics. Every action still uses its ordinary ownership/distance/save gates.
"""
from copy import deepcopy

import machine_routine
import machine_tools
import machine_witness
import world_goods
from mcp import progression


def output_action(app,owner):
    """Locate remaining shared output of an actually observed personal batch.

    Observation reserves no goods. Collection still competes for the current
    pile and rechecks ordinary distance/ownership/durable-save gates.
    """
    goods=getattr(getattr(app,'brains',None),'goods',None)
    if goods is None:return None
    evidence=app.journal_for(owner).copy().get('evidence',{})
    for event in reversed(list(evidence.values())):
        if (event.get('passes') is not True or event.get('source')!='watched'
            or not event.get('run','').startswith(app.world_id+':')
            or (event.get('observer') or {}).get('player')!=owner
            or 'machine_goods recipe ledger' not in event.get('models',[])):continue
        brain=app.brains.brains.get(event.get('machine'))
        routine=brain.routine if brain else None
        pile=goods.by_name(routine.output) if routine else None
        if pile is None or pile.get('rack'):continue
        remaining={s:min(kg,float((pile.get('holds') or {}).get(s,0)))
            for s,kg in ((event.get('result') or {}).get('made') or {}).items()
            if kg>0 and float((pile.get('holds') or {}).get(s,0))>=1e-6}
        if remaining:
            return {'verb':'collect-output','label':'Collect available '+', '.join(remaining)+' · '+pile['name'],
                'status':'Available','destination':{'screen':'world','resource':pile['name']},
                'pile':pile['name'],'available_kg':remaining,
                'blockers':[],'limits':'Shared output, not reserved by observation. Get within 2 m to collect.'}
    return None


def choices(app, owner, technique=None):
    session=getattr(getattr(app,'live',None),'session',None)
    goods=getattr(getattr(app,'brains',None),'goods',None)
    if session is None or goods is None or app.live_holder!='world':return []
    registry=app.registry() if callable(getattr(app,'registry',None)) else progression.Registry()
    wanted=None
    if technique:
        skill=registry.techniques.get(technique) or {}
        wanted={c['design'] for route in (skill.get('earned_by') or {}).get('any_of',[])
                for c in route.get('all_of',[]) if c.get('demonstrated') and c.get('design')}
    declared={p['name']:p for p in (app.room.spec.get('machines') or {}).get('programs',[])}
    native={p['name']:p for p in (session.state.get('machines') or {}).get('programs',[])}
    stores={s['id']:s for s in (session.state.get('machines') or {}).get('stores',[])}
    sources=machine_witness.machines(app)
    thermal={}
    if any(app.brains.brains[s['machine']].routine.chamber for s in sources):
        reading=app.live.act({'session':session.id,'op':'thermo'}).get('thermo') or {}
        thermal={r['name']:r for r in reading.get('regions',[])}
    out=[]
    for source in sources:
        routine=app.brains.brains[source['machine']].routine
        intake=goods.by_name(routine.intake)
        output=goods.by_name(routine.output)
        if intake is None or output is None:continue
        recipes=[]
        for recipe in machine_routine.process_options(app.room.spec,routine):
            experiment=progression.batch_design(registry,recipe['name'])
            if experiment is not None and (wanted is None or experiment[0]['id'] in wanted):
                recipes.append(recipe)
        if not recipes:continue
        facts=world_goods.input_readiness(app,owner,intake,{s for r in recipes for s in r['in']})
        quantities={r['substance']:r for r in facts['inputs']}
        program=native[source['machine']]
        store=stores.get(program.get('store'))
        for recipe in recipes:
            inputs=[deepcopy(quantities[s]) for s in recipe['in']]
            own={r['substance']:r['hopper_kg']+r['mass_kg']+r['stored_personal_kg']+r['carried_kg'] for r in inputs}
            hopper=goods.convert(recipe['name'],dict(intake.get('holds') or {}),routine.batch_kg)
            available=goods.convert(recipe['name'],dict(own),routine.batch_kg)
            missing=[r['substance'] for r in inputs if own[r['substance']]<1e-6]
            cold=bool(recipe.get('needs_c')) and (thermal.get(routine.chamber) or {}).get('temperature_k',0)-273.15 < recipe['needs_c']-machine_tools.HEAT_SLACK_C
            heating_j=(routine.element_w or machine_tools.HEATING_W)*machine_tools.HEATING_S if cold else 0.
            charge=store.get('charge_j') if store else None
            power_blocked=store is not None and (charge<heating_j or
                (not cold and charge<.01*float(recipe.get('work_j_per_kg',0))))
            row={'schema':'banjo.process-readiness.v1','machine':source['machine'],
                'body':declared[source['machine']].get('body'),'at_m':source['at_m'],
                'recipe':recipe['name'],'current_recipe':routine.recipe,'power':source['power'],
                'input':intake['name'],'output':output['name'],'inputs':inputs,
                'input_batch_kg':hopper.get('kg_in',0),'available_batch_kg':available.get('kg_in',0),
                'missing':missing,'power_blocked':power_blocked,'stored_charge_j':charge,
                'next_heating_j':heating_j,'cold':cold,
                'pending_inputs':[deepcopy(r) for r in facts['pending'] if r['pile']==intake['name']],
                'limits':'Possible input batch, not a future result. Heat/work, distance, ownership and durable saves recheck at execution.'}
            row['next_action']=_next(row)
            out.append(row)
    return sorted(out,key=lambda r:(not bool(r['available_batch_kg']),r['power_blocked'],
        not (r['recipe']==r['current_recipe'] and bool(r['input_batch_kg'])),
        r['recipe']!=r['current_recipe'],len(r['missing']),r['machine'],r['recipe']))


def _next(row):
    destination={'screen':'world','focus':row['body']}
    action={'verb':'process-input','status':'Available','destination':destination,'blockers':[]}
    def answer(label,**fields):return {**action,'label':label,**fields}
    if row['pending_inputs']:
        return answer('Retry your pending input transfer · '+row['machine'])
    if not row['available_batch_kg']:
        shortage=next((r for r in row['inputs'] if r['substance'] in row['missing']),row['inputs'][0])
        name=shortage['substance']
        source=next((s for s in shortage['sources'] if s['left_kg']>0),None)
        reason=f"{row['input']} intake needs: {', '.join(row['missing'])}"
        if source:
            return answer('Find '+name+' · Mining rover',destination={'screen':'world','resource':source['name']},blockers=[reason])
        if shortage['sources']:reason+='; its known source is exhausted'
        return answer('Find supplies for '+row['recipe'],verb='wait',status='Blocked',blockers=[reason])
    if row['recipe']!=row['current_recipe']:
        return answer(('Stop '+row['machine']+', then choose ' if row['power'] else 'Choose ')+row['recipe'],verb='select-process')
    for item in row['inputs']:
        if item['hopper_kg']>=1e-6:continue
        name=item['substance']
        if item['stored_personal_kg']>=1e-6 or item['mass_kg']>=1e-6:
            return answer('Load '+name+' into '+row['input'])
        if item['carried_kg']>=1e-6:
            return answer('Store '+name+' · Inventory',verb='store-ground',destination={'screen':'inventory'})
    if row['power_blocked']:
        return answer('Check power for '+row['machine'],verb='wait',status='Blocked',
            blockers=['Its measured battery cannot fund the next heating/work step'])
    if not row['power']:
        return answer('Turn on '+row['machine']+' · '+row['recipe'],verb='power-on')
    return answer('Watch next '+row['recipe']+' batch · '+row['machine'],verb='watch-batch')
