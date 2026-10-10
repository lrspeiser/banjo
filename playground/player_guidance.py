"""One authenticated next action and funded-build reading for game screens.

This describes ordinary actions. It never executes them or certifies placement,
tool strength, manufacturing skill, or a future machine batch.
"""
from copy import deepcopy
import math
import json

import ai_actions
import starter_goals
import workshop_library
import workshop_tabs


def validate_project(value):
    """A bounded authoring proposal, never client-supplied game state."""
    from mcp import workshop_components
    if not isinstance(value,dict) or set(value)-{'name','candidate','selection'}:
        raise ValueError('A project needs its name, bounded design and optional Lab selection')
    name=value.get('name')
    if not isinstance(name,str) or not 1<=len(name)<=160:
        raise ValueError('Project name must be 1–160 characters')
    candidate=value.get('candidate')
    if not isinstance(candidate,dict) or set(candidate)-{'kind','parameters','component_overrides','design_id','purpose'}:
        raise ValueError('Supply design inputs, not stock, price, skill or readiness claims')
    try:encoded=json.dumps(value,allow_nan=False)
    except (TypeError,ValueError) as error:raise ValueError('Project must contain finite JSON design inputs') from error
    # Leave room for the action envelope within the existing 32 KiB HTTP limit.
    if len(encoded.encode('utf-8'))>24*1024:raise ValueError('Project exceeds the 24 KiB authoring budget')
    # A design the Workshop cannot assemble -- a parameter its kind does not
    # take, a wrong type -- is a bad request like any other here, not an
    # exception that drops the player's connection without an answer.
    try:workshop_components.design_from_spec(candidate)
    except (KeyError,TypeError) as error:raise ValueError(f'Project design is not buildable: {error}') from error
    selection=value.get('selection')
    if selection is not None and (not isinstance(selection,dict) or set(selection)!={'source','id'}
        or selection['source'] not in ('carried','recipe','saved','library')
        or not isinstance(selection['id'],str) or not 1<=len(selection['id'])<=160):
        raise ValueError('Invalid Lab selection')
    return deepcopy(value)


def _project_key(app,owner):return (app.world_id,owner,app.room.scene)


def clear_project(app,owner):
    with workshop_library._connect(app) as db:
        db.execute('DELETE FROM player_guidance_projects WHERE world_id=? AND owner_id=? AND scene=?',_project_key(app,owner))


def set_project(app,owner,value):
    import inventory_room
    value=validate_project(value)
    selection=value.get('selection') or {}
    if selection.get('source')=='carried':
        shown=inventory_room.shown(app,owner)
        if not any(item and item['id']==selection['id'] for item in [*shown.get('stowed',[]),*shown.get('hands',{}).values()]):
            raise ValueError('Select your own carried item in Inventory first')
    # New work after selection completes the intent. Earlier copies do not
    # prevent explicitly choosing the same design for another paid build.
    value['prior_jobs']=list((getattr(app.room,'fabrication_record',None) or {}).get('jobs',{}))
    with workshop_library._connect(app) as db:
        db.execute('INSERT INTO player_guidance_projects VALUES (?,?,?,?) '
            'ON CONFLICT(world_id,owner_id,scene) DO UPDATE SET payload_json=excluded.payload_json',
            (*_project_key(app,owner),json.dumps(value,allow_nan=False)))


def selected_project(app,owner,process):
    from mcp.fabrication import digest
    with workshop_library._connect(app) as db:
        row=db.execute('SELECT payload_json FROM player_guidance_projects WHERE world_id=? AND owner_id=? AND scene=?',
            _project_key(app,owner)).fetchone()
    if row is None:return None
    value=json.loads(row['payload_json'])
    for ident,job in (process or {}).get('jobs',{}).items():
        binding=job.get('make_source') or job.get('remake_source') or {}
        # The browser's generation counter identifies a preview take, not a
        # physical design input. It is present in paid quotes/jobs but omitted
        # from the persisted guidance selection. Keep exact design fields and
        # owner/job boundaries while comparing the same authored candidate.
        authored={k:v for k,v in job['candidate'].items() if k!='generation'}
        if ident not in value.get('prior_jobs',[]) and binding.get('owner')==owner and digest(authored)==digest(value['candidate']):
            clear_project(app,owner);return None
    return validate_project({k:v for k,v in value.items() if k!='prior_jobs'})


def _project_plan(app,value,offers,balance):
    import market
    from mcp import workshop_components
    design,_=workshop_components.design_from_spec(value['candidate'])
    stocks={r['material']:r for r in workshop_library.rack(app)['materials']}
    goods={r['substance']:r for r in workshop_library.goods_rack(app)['goods']}
    def line(name,kg,stock,kind):
        held=stock.get(name,{})
        return {kind:name,'kg':kg,'held_kg':held.get('mass_kg',0),
            'personal_kg':held.get('personal_kg',0),'shared_kg':held.get('shared_kg',0)}
    recipe={**value['candidate'],'name':value['name'],'source':'selected',
        'materials':[line(r['material'],r['mass_kg'],stocks,'material') for r in workshop_library.bill_of_materials(app,design)['materials']],
        'goods':[line(n,kg,goods,'substance') for n,kg in workshop_library.goods_needed(design).items()]}
    plan=market._build_plan(recipe,offers,balance)
    plan.update(candidate=deepcopy(value['candidate']),focused=True,selection=value.get('selection'))
    return plan


def _project_action(state,project,reading):
    destination={'screen':'lab','selection':project.get('selection')}
    status=reading['status']
    if status=='Supplies missing':
        shortage=next(line for line in reading['lines'] if line['short_kg']>1e-10)
        supply_state={**state,'goals':{'next_goal':'project-supply','goals':[{'id':'project-supply',
            'requirement':{'kind':'personal-stock','material':shortage['substance'],'minimum_kg':shortage['short_kg']}}]}}
        actions=ai_actions.catalog(supply_state,{})
        action=deepcopy(next(a for a in actions if a['id']==ai_actions.reference_pick(supply_state,actions)))
        action['destination']=_destination(action,project)
        action['status']='Blocked' if action['verb']=='wait' else 'Available'
        return action
    label='Prepare supplies' if status in ('Fund materials','Fund energy') else status
    return {'verb':'review-project','label':label+' · '+project['name'],
        'status':'Blocked' if status in ('Needs changes','Workbench missing','Workbench in use','Workpiece limit reached') else 'Available',
        'destination':destination,'blockers':[reading['reason']] if reading.get('reason') else []}


def for_design(app,candidate):
    """Fresh authenticated observations for an isolated Lab chat candidate."""
    if not getattr(app,'world_id',None):
        return {'available':False,'reason':'Open a named World for actual workbench guidance'}
    return resolve(app,workshop_library.rack_owner_id(app),project_override={
        'name':str(candidate.get('purpose') or candidate['kind'])[:160],'candidate':candidate})


def build_readiness(quote, state, stock_sources=(), goods_sources=(), *, candidate=None):
    """The same station gates as paid Make, using its exact reviewed quote."""
    from mcp.fabrication import MAX_JOBS
    required=quote.get('stock_materials_kg') or {quote['material']:quote['stock_kg']}
    lines=[]
    raw_materials=(quote.get('raw_matter') or {}).get('materials_kg',{})
    for needs,held,sources,kind in ((required,state['stock_kg'],stock_sources,'material'),
                                  (quote.get('assembly_goods_kg',{}),state.get('goods_stock_kg',{}),goods_sources,'goods')):
        for name,kg in needs.items():
            raw_kg=raw_materials.get(name,0.) if kind=='material' else 0.
            gap=max(0.,kg-held.get(name,0.)-raw_kg)
            personal=sum(s['mass_kg'] for s in sources if s['material']==name and s['pool']=='personal')
            shared=sum(s['mass_kg'] for s in sources if s['material']==name and s['pool']=='shared')
            lines.append({'substance':name,'kind':kind,'needed_kg':kg,'station_kg':min(kg,held.get(name,0.)),
                'native_raw_kg':raw_kg,
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
    result={'schema':'banjo.build-readiness.v1','basis':'reviewed native manufacture quote',
        'status':status,'ready_to_start':not (unfunded or energy>1e-10 or busy or budget_full),
        'lines':lines,'energy_required_j':quote['supply_required_j'],
        'station_energy_j':state['energy_j'],'fund_energy_j':energy,'occupied':busy,'workpiece_limit_reached':budget_full,
        'minimum_duration_s':quote['minimum_duration_s'],
        'product_mass_kg':quote.get('product_kg'),'cell_m':quote.get('cell_m'),
        'occupied_cells':quote.get('cells'),
        'raw_matter':deepcopy(quote.get('raw_matter')),
        'skills_required':[],'placement_checked':False,'functional_test_required':True}
    candidate=candidate if candidate is not None else quote.get('candidate')
    if candidate is not None:
        from mcp import workshop_components,workshop_placement
        design,_=workshop_components.design_from_spec(candidate)
        result['installation']=workshop_placement.for_design(design)
    return result


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


def _carried_surface_action(owner, requirement, process, inventory):
    """Suggest placing an owned paid surface; placement still earns the goal."""
    if (requirement or {}).get('kind')!='funded-box-surface':return None
    slots=(inventory.get('record') or {}).get('stowed',[])
    for job in (process or {}).get('jobs',{}).values():
        binding=job.get('make_source') or job.get('remake_source') or {}
        if binding.get('owner')!=owner or job.get('status')!='installed':continue
        if not ai_actions.fits_requirement(job['candidate'],requirement):continue
        root=job.get('root_body')
        for where,item in [*inventory.get('hands',{}).items(),*[('stowed',i) for i in inventory.get('stowed',[])]]:
            if not item or not root or root not in [item['id'],*item.get('parts',[])]:continue
            name=item.get('name') or root
            if where=='stowed':
                slot=slots.index(item['id']) if item['id'] in slots else None
                key=f'Key {(slot+1)%10}' if slot is not None else 'World quick slot'
                label=f'Equip {name} · {key}, then place it in World'
            else:label=f'Place held {name} · E'
            return {'verb':'place-product','label':label,'status':'Available',
                'destination':{'screen':'world','focus':item['id']}}
    return None


def _camp_light(app,owner,native):
    """Actual owned paid variant and its current use; display names award nothing."""
    import goal_chains
    import product_labels
    import inventory_room
    candidate=goal_chains.camp_light_recipe()
    key=product_labels.source_key(candidate)
    for receipt in reversed(getattr(app.room,'workshop_installs',[]) or []):
        if (receipt.get('status')!='installed' or receipt.get('owner_id')!=owner
            or not receipt.get('resources_charged') or not receipt.get('native_precise_geometry_verified')):continue
        try:matched=product_labels.source_key(receipt.get('recipe') or {})==key
        except (ValueError,KeyError,TypeError):matched=False
        if not matched:continue
        roots=set(receipt.get('root_bodies') or [receipt.get('root_body')])
        shown=inventory_room.shown(app,owner)
        for item in shown.get('stowed',[]):
            if item['id'] in roots:
                return candidate,{'verb':'place-product','label':'Equip Camp light from your quick slot, then place it',
                    'status':'Available','destination':{'screen':'world','focus':item['id']}},True
        held=next((item for item in shown.get('hands',{}).values() if item and item['id'] in roots),None)
        if held:
            return candidate,{'verb':'place-product','label':'Place held Camp light · E',
                'status':'Available','destination':{'screen':'world','focus':held['id']}},True
        lamp=next((l for l in (native.get('machines') or {}).get('lamps',[]) if l['body'] in roots),None)
        if lamp and not lamp.get('lit'):
            store=next((s for s in (native.get('machines') or {}).get('stores',[]) if s['id']==lamp.get('store')),None)
            empty=store is None or store['charge_j']<=0
            return candidate,{'verb':'use-product','label':('Recharge' if empty else 'Switch on')+' Camp light · World',
                'status':'Blocked' if empty else 'Available','destination':{'screen':'world','focus':receipt['root_body']},
                'blockers':['Battery empty; connect an actual power source'] if empty else []},True
        return candidate,None,True
    return candidate,None,False


def resolve(app, owner, *, offers=None, balance=None, focus=None, project_override=None):
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
            process=deepcopy(getattr(app.room,'fabrication_record',None))
            selected=validate_project(project_override) if project_override is not None else selected_project(app,owner,process)
            if not selected and native and getattr(app,'world_id',None):
                import construction_projects
                construction=construction_projects.guidance(app,owner)
                if construction:return construction
            project=_project_plan(app,selected,offers,balance) if selected else market._recommend(book['templates'],offers,balance,goals)
            follow_up=False;use_light=None
            next_kind=((next((g for g in goals['goals'] if g['id']==goals['next_goal']),None) or {})
                       .get('requirement') or {}).get('kind')
            # Lighting the camp is now a goal of its own; the light is offered
            # as soon as it is next, not only after every chapter is done.
            if (goals['complete'] or next_kind=='own-light-used') and not selected:
                from mcp import workshop_components
                candidate,use_light,already=_camp_light(app,owner,native)
                design,_=workshop_components.design_from_spec(candidate)
                glass=next((r for r in workshop_library.rack(app)['materials'] if r['material']=='glass'),{})
                needed=next(r['mass_kg'] for r in workshop_library.bill_of_materials(app,design)['materials'] if r['material']=='glass')
                owned_glass=glass.get('personal_kg',0)+((process or {}).get('stock_kg') or {}).get('glass',0)
                if not already and owned_glass+1e-9>=needed:
                    project=_project_plan(app,{'name':'Camp light','candidate':candidate,
                        'selection':{'source':'recipe','id':'mine-lamp:Camp light'}},offers,balance)
                    project['focused']=False;follow_up=True
            elif next_kind=='own-solar-collected' and not selected:
                import goal_chains
                project=_project_plan(app,{'name':'Camp solar panel','candidate':goal_chains.camp_solar_recipe(),
                    'selection':{'source':'recipe','id':'solar-array:Camp solar panel'}},offers,balance)
                project['focused']=False;follow_up=True
            row=next((g for g in goals['goals'] if g['id']==goals['next_goal']),None)
            state={'goals':goals,'skills':skills,'recipes':book['templates'],
                'stockpiles':book['stockpiles'],'pose':deepcopy((player_world.records(app).get(owner) or {}).get('pose')),
                'native':{'session':session.id if session else None,**native},
                'market':{'offers':offers,'balance_j':balance,'bankable':bool(native)},'balance_j':balance}
            processing=None
            if row and (row.get('requirement') or {}).get('kind')=='personal-batch':
                import process_guidance
                options=process_guidance.choices(app,owner,(row.get('requirement') or {}).get('technique'))
                processing=options[0] if options else None
                state['processing_readiness']=processing
            memory={}
            reading=None
            if project and process is not None and native:
                fabrication.advance(process,native['t'])
                try:
                    quote=fabrication_remake.minimum_quote(app,project['candidate'],process,session.spec['cell_m'])
                    reading=build_readiness(quote,process,fabrication_stock.sources(app),fabrication_stock.sources(app,'goods'),
                        candidate=project['candidate'])
                    project['build_readiness']=reading
                    if selected:
                        # Market estimates only what remains to purchase. Stock
                        # already funded at this station must not be bought again.
                        recipe={**project['candidate'],'name':project['name'],'source':'selected','materials':[],'goods':[]}
                        for line in reading['lines']:
                            recipe['materials' if line['kind']=='material' else 'goods'].append({
                                'material' if line['kind']=='material' else 'substance':line['substance'],
                                'kg':line['fund_kg'],'held_kg':line['personal_kg']+line['shared_kg'],
                                'personal_kg':line['personal_kg'],'shared_kg':line['shared_kg']})
                        project.update(market._build_plan(recipe,offers,balance))
                        project['candidate']=deepcopy(selected['candidate'])
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
                selected_recipe=next((r for r in comparison['comparison'] if r['candidate']==project['candidate']),None)
                if selected_recipe:
                    memory.update(comparison_signature=comparison['signature'],selected_recipe=selected_recipe['id'])
                    actions=ai_actions.catalog(state,memory)
            targets=[a['target'] for a in actions if a['verb']=='select-target']
            if targets:
                focused=next((t for t in targets if t.get('body')==focus),None)
                chosen=focused or min(targets,key=lambda t:(bool(t.get('needs')),ai_actions._distance(state['pose'],t['at_m'])))
                memory['selected_target']=chosen
                actions=[a for a in ai_actions.catalog(state,memory) if a['verb']!='select-target']
            chosen=next((a for a in actions if a['id']==ai_actions.reference_pick(state,actions)),None)
            next_action=deepcopy(chosen) if chosen else None
            if selected and reading:next_action=_project_action(state,project,reading)
            elif row and (row.get('requirement') or {}).get('kind')=='personal-batch':
                if processing:
                    next_action=deepcopy(processing['next_action'])
                    project=None;reading=None
            elif row and (row.get('requirement') or {}).get('kind')=='funded-box-surface':
                import inventory_room
                placement=_carried_surface_action(owner,row['requirement'],process,inventory_room.shown(app,owner))
                if placement:next_action=placement;project=None;reading=None
            if next_action:
                next_action.setdefault('destination',_destination(next_action,project))
                next_action.setdefault('status','Blocked' if next_action['verb']=='wait' else 'Available')
                if next_action['verb']=='build' and reading:
                    label='Prepare supplies' if reading['status'] in ('Fund materials','Fund energy') else reading['status']
                    next_action['label']=('Review '+project['name']+' in Lab' if reading.get('status')=='Needs changes' else
                                          label+' · '+project['name'])
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
            if goals['complete'] and not selected:
                import process_guidance
                output=process_guidance.output_action(app,owner)
                next_action=use_light or output or (_project_action(state,project,reading) if follow_up and reading else
                    {'verb':'explore','label':'Choose another supported skill or design',
                     'status':'Available','destination':{'screen':'skills'}})
                if output or use_light:project=None;reading=None
            own_jobs=[(ident,j) for ident,j in (process or {}).get('jobs',{}).items()
                if ((j.get('make_source') or j.get('remake_source') or {}).get('owner')==owner
                    and j['status'] in ('running','paused','ready'))]
            draft_project=deepcopy(project) if project_override is not None else None
            if own_jobs:
                ident,job=own_jobs[-1]
                reading={'schema':'banjo.build-readiness.v1','ready_to_start':False,
                    'status':{'running':'Making','paused':'Paused','ready':'Output ready'}[job['status']],
                    'work_j':job['work_j'],'required_j':job['required_j'],'placement_checked':False}
                next_action={'verb':'continue-build','status':'Available',
                    'label':{'running':'Watch your workpiece finish','paused':'Resume your workpiece',
                             'ready':'Collect your finished workpiece'}[job['status']],
                    'destination':{'screen':'lab','job':ident}}
                # Pending work is the accepted candidate, not another shopping
                # recommendation. No price or new funding is implied here.
                project={'name':'Your workpiece','source':'workpiece','job_id':ident,
                    'candidate':deepcopy(job['candidate']),'focused':False,'lines':[],
                    'estimated_total_j':None,'affordable':False,'energy_gap_j':None,
                    'declared_uses':[],'goal':None}
            if not native:
                next_action={'verb':'open-world','label':'Open your saved World','status':'Available',
                    'destination':{'screen':'world'}}
            if project:project['build_readiness']=reading
            result={'schema':'banjo.player-guidance.v1','observed_native_t_s':native.get('t'),
                'chain_id':goals['chain_id'],'goal':({'id':row['id'],'title':row['title']} if row else None),
                'next_action':next_action,'project':project,'build_readiness':reading,
                'processing_readiness':processing,
                'limits':'Snapshot only. Actions recheck stock, ownership, native admission and placement.'}
            if project_override is not None:result['draft_project']=draft_project
            return result
        finally:workshop_library.REQUEST_OWNER.reset(token)
