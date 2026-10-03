"""One authenticated next action and funded-build reading for game screens.

This describes ordinary actions. It never executes them or certifies placement,
tool strength, manufacturing skill, or a future machine batch.
"""
from copy import deepcopy
import math

import ai_actions
import starter_goals
import workshop_library
import workshop_tabs


def build_readiness(quote, state, stock_sources=(), goods_sources=()):
    """The same station gates as paid Make, using its exact reviewed quote."""
    from mcp.fabrication import MAX_JOBS
    required=quote.get('stock_materials_kg') or {quote['material']:quote['stock_kg']}
    lines=[]
    for needs,held,sources,kind in ((required,state['stock_kg'],stock_sources,'material'),
                                  (quote.get('assembly_goods_kg',{}),state.get('goods_stock_kg',{}),goods_sources,'goods')):
        for name,kg in needs.items():
            gap=max(0.,kg-held.get(name,0.))
            personal=sum(s['mass_kg'] for s in sources if s['material']==name and s['pool']=='personal')
            shared=sum(s['mass_kg'] for s in sources if s['material']==name and s['pool']=='shared')
            lines.append({'substance':name,'kind':kind,'needed_kg':kg,'station_kg':min(kg,held.get(name,0.)),
                'fund_kg':gap,'personal_kg':personal,'shared_kg':shared,
                'short_kg':max(0.,gap-personal-shared)})
    energy=max(0.,quote['supply_required_j']-state['energy_j'])
    busy=any(j['status']=='running' for j in state['jobs'].values())
    budget_full=len(state['jobs'])>=MAX_JOBS
    unfunded=any(r['fund_kg']>1e-10 for r in lines)
    short=any(r['short_kg']>1e-10 for r in lines)
    status=('Supplies missing' if short else 'Fund materials' if unfunded else
            'Fund energy' if energy>1e-10 else 'Workbench in use' if busy else
            'Workpiece limit reached' if budget_full else 'Ready to make')
    return {'schema':'banjo.build-readiness.v1','basis':'reviewed native manufacture quote',
        'status':status,'ready_to_start':not (unfunded or energy>1e-10 or busy or budget_full),
        'lines':lines,'energy_required_j':quote['supply_required_j'],
        'station_energy_j':state['energy_j'],'fund_energy_j':energy,'occupied':busy,'workpiece_limit_reached':budget_full,
        'minimum_duration_s':quote['minimum_duration_s'],
        'skills_required':[],'placement_checked':False,'functional_test_required':True}


def _destination(action, project=None):
    target=action.get('target') or {}
    verb=action['verb']
    route={'screen':'world'}
    if action.get('pile'):route['resource']=action['pile']
    if target.get('body'):route['focus']=target['body']
    if verb in ('move','use-tool') and target.get('ground_at_m'):
        at=target['ground_at_m'];route={'screen':'world','ground':[at[0],at[2]]}
    if verb in ('buy','bank'):route={'screen':'market'}
    elif verb in ('build','compare-recipes','select-recipe','continue-build'):
        route={'screen':'recipes','recipe':project['name']} if project else {'screen':'recipes'}
    elif verb=='wait':route={'screen':'goals'}
    return route


def resolve(app, owner, *, offers=None, balance=None, focus=None):
    """Call under the world's state lock; all personal reads bind to owner."""
    import market
    import player_world
    import world_access
    import fabrication_remake
    import fabrication_stock
    from mcp import fabrication
    with world_access.state_lock(app):
        token=workshop_library.REQUEST_OWNER.set(owner)
        try:
            if offers is None or balance is None:
                wallet=market.request(app,owner,{'action':'view'},lambda *_:False,include_guidance=False)
                offers,balance=wallet['offers'],wallet['balance_j']
            session=getattr(app.live,'session',None)
            native=(session.state or {}) if session and app.live_holder=='world' else {}
            goals=starter_goals.view(app,owner,{'chain':'active'})
            book=workshop_tabs.recipes(app)
            skills=workshop_tabs.skills(app)['techniques']
            project=market._recommend(book['templates'],offers,balance,goals)
            row=next((g for g in goals['goals'] if g['id']==goals['next_goal']),None)
            state={'goals':goals,'skills':skills,'recipes':book['templates'],
                'stockpiles':book['stockpiles'],'pose':deepcopy((player_world.records(app).get(owner) or {}).get('pose')),
                'native':{'session':session.id if session else None,**native},
                'market':{'offers':offers,'balance_j':balance,'bankable':bool(native)},'balance_j':balance}
            memory={}
            reading=None
            process=deepcopy(getattr(app.room,'fabrication_record',None))
            if project and process is not None and native:
                fabrication.advance(process,native['t'])
                try:
                    quote=fabrication_remake.minimum_quote(app,project['candidate'],process,session.spec['cell_m'])
                    reading=build_readiness(quote,process,fabrication_stock.sources(app),fabrication_stock.sources(app,'goods'))
                    project['build_readiness']=reading
                except ValueError as error:
                    reading={'schema':'banjo.build-readiness.v1','ready_to_start':False,
                        'status':'Needs changes','reason':str(error),'placement_checked':False}
                    project['build_readiness']=reading
            elif project:
                reading={'schema':'banjo.build-readiness.v1','ready_to_start':False,
                    'status':'Open World' if not native else 'Workbench missing','placement_checked':False}
                project['build_readiness']=reading
            # Normalize planning-only choices without changing the game or AI
            # character's memory. People follow the same observed capability lane.
            actions=ai_actions.catalog(state,memory)
            comparison=next((a for a in actions if a['verb']=='compare-recipes'),None)
            if comparison and project:
                selected=next((r for r in comparison['comparison'] if r['candidate']==project['candidate']),None)
                if selected:
                    memory.update(comparison_signature=comparison['signature'],selected_recipe=selected['id'])
                    actions=ai_actions.catalog(state,memory)
            targets=[a['target'] for a in actions if a['verb']=='select-target']
            if targets:
                focused=next((t for t in targets if t.get('body')==focus),None)
                chosen=focused or min(targets,key=lambda t:(bool(t.get('needs')),ai_actions._distance(state['pose'],t['at_m'])))
                memory['selected_target']=chosen
                actions=[a for a in ai_actions.catalog(state,memory) if a['verb']!='select-target']
            chosen=next((a for a in actions if a['id']==ai_actions.reference_pick(state,actions)),None)
            next_action=deepcopy(chosen) if chosen else None
            if next_action:
                next_action['destination']=_destination(next_action,project)
                next_action['status']='Blocked' if next_action['verb']=='wait' else 'Available'
                if next_action['verb']=='build' and reading:
                    next_action['label']=('Review '+project['name']+' in Lab' if reading.get('status')=='Needs changes' else
                                          reading['status']+' · '+project['name'])
                    next_action['destination']={'screen':'recipes','recipe':project['name']}
                    if reading.get('reason'):next_action['blockers']=[reading['reason']]
                    if reading.get('status') in ('Needs changes','Workbench missing','Open World'):
                        next_action['status']='Blocked'
                if next_action['verb']=='bank':
                    solar=next((s for s in (native.get('machines') or {}).get('stores',[]) if s['body']=='solar farm'),None)
                    bankable=max(0.,solar['charge_j']-.05*solar['capacity_j']) if solar else 0.
                    if bankable<1:
                        next_action.update(verb='wait',status='Blocked',label='Wait for shared solar energy',
                            blockers=['No measured shared solar energy is available above its reserve'])
                    else:next_action['label']=f'Bank {min(500,math.floor(bankable))} J from the shared farm'
                import product_labels
                labels=product_labels.body_labels(app)
                for raw,label in labels.items():
                    next_action['label']=next_action['label'].replace(raw,label)
                if next_action['verb']=='acquire' and (next_action.get('target') or {}).get('where')=='stowed':
                    next_action['label']+=' · World quick slot'
            if goals['complete']:
                next_action={'verb':'explore','label':'Choose another supported skill or design',
                    'status':'Available','destination':{'screen':'skills'}}
            own_jobs=[(ident,j) for ident,j in (process or {}).get('jobs',{}).items()
                if ((j.get('make_source') or j.get('remake_source') or {}).get('owner')==owner
                    and j['status'] in ('running','paused','ready'))]
            if own_jobs:
                ident,job=own_jobs[-1]
                reading={'schema':'banjo.build-readiness.v1','ready_to_start':False,
                    'status':{'running':'Making','paused':'Paused','ready':'Output ready'}[job['status']],
                    'work_j':job['work_j'],'required_j':job['required_j'],'placement_checked':False}
                next_action={'verb':'continue-build','status':'Available',
                    'label':{'running':'Watch your workpiece finish','paused':'Resume your workpiece',
                             'ready':'Collect your finished workpiece'}[job['status']],
                    'destination':{'screen':'lab','job':ident}}
            if not native:
                next_action={'verb':'open-world','label':'Open your saved World','status':'Available',
                    'destination':{'screen':'world'}}
            return {'schema':'banjo.player-guidance.v1','observed_native_t_s':native.get('t'),
                'chain_id':goals['chain_id'],'goal':({'id':row['id'],'title':row['title']} if row else None),
                'next_action':next_action,'project':project,'build_readiness':reading,
                'limits':'Snapshot only. Actions recheck stock, ownership, native admission and placement.'}
        finally:workshop_library.REQUEST_OWNER.reset(token)
