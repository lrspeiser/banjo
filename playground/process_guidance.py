"""Read-only paths to a positive supported batch using current private supplies.

Recipe-ledger conversions and reported avatar views are not chemistry or body
physics. Every action still uses its ordinary ownership/distance/save gates.
"""
from copy import deepcopy
import math

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
    import player_world
    pose=(player_world.records(app).get(owner) or {}).get('pose') or {}
    watching=(getattr(app,'machine_observers',{}) or {}).get(owner) or {}
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
            own={r['substance']:r['hopper_kg']+r['mass_kg']+r['stored_personal_kg']+r['carried_kg']+r.get('pile_kg',0) for r in inputs}
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
                'input_at_m':[intake['at_m'][0],source['at_m'][1],intake['at_m'][1]],
                'stored':[deepcopy(r) for r in facts['stored'] if r['substance'] in recipe['in'] and r['pool']=='personal'],
                'raw_revision':facts['raw_revision'],'batch_kg':routine.batch_kg,
                'input_batch_kg':hopper.get('kg_in',0),'available_batch_kg':available.get('kg_in',0),
                'missing':missing,'power_blocked':power_blocked,'stored_charge_j':charge,
                'next_heating_j':heating_j,'cold':cold,
                'pending_inputs':[deepcopy(r) for r in facts['pending'] if r['pile']==intake['name']],
                'ports_in_reach':all(goods.stockpile_near(source['at_m'][0],source['at_m'][2],named=p['name'])
                    is not None for p in (intake,output)),
                'limits':'Possible input batch, not a future result. Heat/work, distance, ownership and durable saves recheck at execution.'}
            row['watching']=watching.get('machine')==source['machine'] and watching.get('until_t',0)>session.state['t']
            row['next_action']=_next(row,pose)
            out.append(row)
    return sorted(out,key=lambda r:(not r['ports_in_reach'],not bool(r['available_batch_kg']),r['power_blocked'],
        not (r['recipe']==r['current_recipe'] and bool(r['input_batch_kg'])),
        r['recipe']!=r['current_recipe'],len(r['missing']),r['machine'],r['recipe']))


def _next(row,pose=None):
    destination={'screen':'world','focus':row['body']}
    action={'verb':'process-input','status':'Available','destination':destination,'blockers':[],
        'target':{k:row[k] for k in ('machine','body','at_m')},'recipe':row['recipe']}
    def answer(label,**fields):return {**action,'label':label,**fields}
    def approach(at,reach,label,resource=None):
        eyes=(pose or {}).get('eyes_m')
        if eyes and math.hypot(eyes[0]-at[0],eyes[2]-at[2])>reach:
            return answer(label,verb='move',aim=at,stand_off_m=1.2,
                destination={'screen':'world','resource':resource} if resource else destination)
    if row['pending_inputs']:
        pending=row['pending_inputs'][0];substance,mass=next(iter(pending['goods'].items()))
        return answer('Retry your pending input transfer · '+row['machine'],operation='deliver-input',
            transfer={'pile':row['input'],'substance':substance,'mass_kg':mass,'request_id':pending['request_id']})
    if not row.get('ports_in_reach',True):
        return answer('Check '+row['machine']+' input/output position',verb='wait',status='Blocked',
            blockers=['The machine cannot reach its input or output pile from its actual position'])
    if not row['available_batch_kg']:
        shortage=next((r for r in row['inputs'] if r['substance'] in row['missing']),row['inputs'][0])
        name=shortage['substance']
        source=next((s for s in shortage['sources'] if s['left_kg']>0),None)
        reason=f"{row['input']} intake needs: {', '.join(row['missing'])}"
        if source:
            return answer('Find '+name+' · Mining rover',operation='find-source',
                destination={'screen':'world','resource':source['name']},blockers=[reason])
        if shortage['sources']:reason+='; its known source is exhausted'
        return answer('Find supplies for '+row['recipe'],verb='wait',status='Blocked',blockers=[reason])
    if row['recipe']!=row['current_recipe']:
        close=approach(row['at_m'],1.8,'Approach '+row['machine'])
        if close:return close
        if row['power']:return answer('Stop '+row['machine']+' to choose '+row['recipe'],verb='power-off')
        return answer('Choose '+row['recipe'],verb='select-process',expected_recipe=row['current_recipe'])
    for item in row['inputs']:
        if item['hopper_kg']>=1e-6:continue
        name=item['substance']
        if item['stored_personal_kg']>=1e-6 or item['mass_kg']>=1e-6:
            close=approach(row['input_at_m'],1.8,'Approach '+row['input'],row['input'])
            if close:return close
            lot=next((r for r in row['stored'] if r['substance']==name and r['mass_kg']>=1e-6),None)
            transfer={'pile':row['input'],'substance':name,
                'mass_kg':math.floor((min(world_goods.MAX_DELIVERY_KG,row['batch_kg'],lot['mass_kg'],item['stored_personal_kg'])
                    if lot else min(world_goods.MAX_DELIVERY_KG,row['batch_kg'],item['mass_kg']))*1e6)/1e6}
            if lot:transfer.update(lot_id=lot['lot_id'],revision=row['raw_revision'])
            return answer('Load '+name+' into '+row['input'],operation='deliver-input',transfer=transfer)
        if item['carried_kg']>=1e-6:
            return answer('Store '+name+' · Inventory',verb='store-ground',destination={'screen':'inventory'},
                quantities={name+'_m3':item['carried_m3']},revision=row['raw_revision'])
        if item.get('piles'):
            pile=item['piles'][0]
            return answer('Collect '+name+' · nearby pile',verb='collect',pile=pile['name'],
                at_m=list(pile['at_m']),destination={'screen':'world','resource':pile['name']})
    if row['power_blocked']:
        return answer('Check power for '+row['machine'],verb='wait',status='Blocked',
            blockers=['Its measured battery cannot fund the next heating/work step'])
    close=approach(row['at_m'],1.8,'Approach '+row['machine'])
    if close:return close
    if not row['power']:
        return answer('Turn on '+row['machine']+' · '+row['recipe'],verb='power-on')
    return answer(('Watch '+row['recipe']+' progress' if row.get('watching') else 'Watch next '+row['recipe']+' batch')+
        ' · '+row['machine'],verb='observe' if row.get('watching') else 'watch-batch')
