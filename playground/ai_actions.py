"""Observed, bounded player actions; planner choices cannot manufacture evidence.

Goal requirements select capabilities, not item names or tutorial step ids.
Targets, prices, recipes and blockers are refreshed from authenticated views.
"""
from copy import deepcopy
import hashlib
import heapq
import json
import math
from mcp import interaction_points, workshop_components, workshop_rigid, workshop_tools


def key(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()[:16]


def candidate(recipe):
    return {k:deepcopy(recipe.get(k,{})) for k in ('kind','parameters','component_overrides')}


def fits_requirement(recipe,requirement):
    if recipe.get('problem'):return False
    if requirement['kind']=='admitted-recipe':
        return candidate(recipe)==candidate(requirement['candidate'])
    if requirement['kind'] not in ('funded-box-surface','ground-tool','funded-ground-tool'):return False
    try:
        design,overrides=workshop_components.design_from_spec(candidate(recipe))
        if requirement['kind'] in ('ground-tool','funded-ground-tool'):return workshop_tools.frame(design) is not None
        workshop_rigid.compile_rigid(design,overrides)
        # The compiler checks exact axis-aligned boxes. Native commit and the
        # goal's saved physical-face predicate are still required afterwards.
        return any(p['kind']=='surface' and p['size_m'][0]*p['size_m'][2]>=requirement['minimum_area_m2']
                   for p in interaction_points.for_design(design))
    except (ValueError,KeyError):return False


def recipe_comparison(state,requirement):
    rows=[]
    for recipe in state.get('recipes',[]):
        if not fits_requirement(recipe,requirement):continue
        rows.append({'id':key(candidate(recipe)), 'name':recipe['name'],
            'candidate':candidate(recipe),'ready':bool((recipe.get('readiness') or {}).get('ready_as_drawn')),
            'enough':bool(recipe.get('enough')),'missing':deepcopy(recipe.get('missing',[])),
            'mass_kg':recipe.get('wants_kg',0), 'declared_uses':recipe.get('can_do',[])})
    return sorted(rows,key=lambda r:(not r['ready'],not r['enough'],sum(m['short_kg'] for m in r['missing']),r['mass_kg'],r['name']))[:12]


def requirement_of(goals):
    return next((g.get('requirement') for g in goals['goals'] if g['id']==goals['next_goal']),None)


def model_view(state,actions,history):
    """Decision evidence only: do not send terrain/render meshes or raw spec.

    Native geometry still authoritatively gates execution on the server. The
    provider needs current choices and blockers, not a renderer's complete map.
    """
    goals=state['goals']
    summary={k:deepcopy(goals.get(k)) for k in ('chain_id','title','complete','next_goal')}
    summary['goals']=[{k:deepcopy(g.get(k)) for k in ('id','title','done','value','target','requirement')}
                      for g in goals['goals']]
    tree=[{k:deepcopy(s.get(k)) for k in ('id','name','known','unmet','within_reach','world_missing','earned_by')}
          for s in state.get('skills',[])]
    inv=state.get('inventory') or {}
    return {'goals':summary,'pose':deepcopy(state.get('pose')),
        'native':{k:state['native'].get(k) for k in ('session','t')},
        'market':{k:deepcopy(state['market'].get(k)) for k in ('balance_j','offers','bankable')},
        'balance_j':state['balance_j'], 'tech_tree':tree,
        'inventory':{'hands':{side:({k:hand.get(k) for k in ('id','name','mass_kg')} if hand else None)
                              for side,hand in inv.get('hands',{}).items()},
                     'stowed':deepcopy((inv.get('record') or {}).get('stowed',[]))},
        'action_catalog':deepcopy(actions),
        'processing_readiness':deepcopy(state.get('processing_readiness')),
        'construction_readiness':deepcopy(state.get('construction_readiness')),
        'construction_project':deepcopy(state.get('construction_project')),
        'recent_actions':[{k:deepcopy(row.get(k)) for k in ('action','label','result','receipt')}
                          for row in history[-4:]]}


def _distance(pose,at):
    eyes=(pose or {}).get('eyes_m') or [0,1.62,3]
    return math.hypot(at[0]-eyes[0],at[2]-eyes[2])


def catalog(state,memory):
    """No game actions here. Choices carry server-observed parameters only."""
    req=requirement_of(state['goals']) or {}
    actions=[]; blockers=[]
    def offer(verb,label,**args):
        ident=verb if not args else verb+':'+key(args)
        actions.append({'id':ident,'verb':verb,'label':label,**deepcopy(args)})
    if memory.get('process_request'):
        offer('continue-process','Retry the retained processing request before transferring more material')
        return actions
    def supplies(missing):
        for gap in missing:
            if gap.get('short_kg',0)<=0:continue
            name=gap['what']
            piles=[p for p in state.get('stockpiles',[]) if not p.get('rack') and p['holds_kg'].get(name,0)>0]
            if piles:
                pile=min(piles,key=lambda p:_distance(state.get('pose'),[p['at_m'][0],0,p['at_m'][1]]))
                at=[pile['at_m'][0],0,pile['at_m'][1]]
                if _distance(state.get('pose'),at)>2:
                    offer('move',f"Approach {pile['name']} for {name}",aim=at,stand_off_m=1.2,pile=pile['name'])
                else:offer('collect',f"Collect nearby {name} from {pile['name']}",pile=pile['name'],at_m=at)
                continue
            lot=next((o for o in state['market']['offers'] if o['substance']==name),None)
            if not lot or lot['remaining']<=0:
                blockers.append(f'Market has no {name} lot in stock');continue
            if state['market']['balance_j']>=lot['price_j']:
                offer('buy',f"Buy {lot['mass_kg']:g} kg {name} for {lot['price_j']} J",item=lot['id'],quoted_price_j=lot['price_j'])
            elif state['market'].get('bankable'):
                if not any(a['verb']=='bank' for a in actions):offer('bank','Bank 500 J from the measured shared solar battery')
            else:blockers.append('Open a solar-powered world before banking energy')
    pending=memory.get('fabrication_build')
    if pending:
        funding=state.get('fabrication') or {}
        process=funding.get('state') or {}
        plan=pending.get('plan') or {}
        # Retry an uncertain write before choosing any new purchase or debit.
        # After review, use current station and personal balances; recipe cards
        # may include shared stock that this autonomous guest cannot spend.
        missing=[]
        if plan and not pending.get('request') and not pending.get('installed') and pending['job_id'] not in process.get('jobs',{}):
            quote=plan['quote']
            for needed,held,sources in (
                (quote.get('stock_materials_kg') or {quote['material']:quote['stock_kg']},
                 process.get('stock_kg',{}),funding.get('stock_sources',[])),
                (quote.get('assembly_goods_kg',{}),process.get('goods_stock_kg',{}),funding.get('goods_sources',[]))):
                for material,kg in needed.items():
                    personal=sum(s['mass_kg'] for s in sources if s['pool']=='personal' and s['material']==material)
                    gap=kg-held.get(material,0)-personal
                    if gap>1e-10:missing.append({'what':material,'short_kg':gap})
        if missing:supplies(missing)
        else:offer('continue-build','Continue the reviewed, funded workpiece before starting another build')
        offer('wait','Stop with the pending workpiece retained',blockers=blockers or ['A reviewed build is pending'])
        return actions
    def building(requirement):
        compared=recipe_comparison(state,requirement)
        signature=key([state['goals']['chain_id'],state['goals']['next_goal'],[(r['id'],r['ready'],r['missing']) for r in compared]])
        if memory.get('comparison_signature')!=signature:
            offer('compare-recipes','Compare compatible recipes, readiness and every material gap',comparison=compared,signature=signature)
        else:
            selected=next((r for r in compared if r['id']==memory.get('selected_recipe')),None)
            if selected is None:
                for row in compared[:6]:
                    if row['ready']:offer('select-recipe',f"Choose {row['name']}",recipe=row)
                if not any(a['verb']=='select-recipe' for a in actions):blockers.append('No compatible recipe is ready on this world grid')
            elif selected['enough']:offer('build',f"Preview and Make {selected['name']} with available supplies",recipe=selected)
            else:supplies(selected['missing'])
    def target_actions(target,kind):
        selected=memory.get('selected_target') or {}
        identity={k:target.get(k) for k in ('body','machine')}
        if {k:selected.get(k) for k in identity}!=identity:
            offer('select-target',f"Select {target.get('machine') or target['body']}",target=target);return
        # Keep a selected ground column fixed while taking/moving the tool.
        if kind=='tool' and selected.get('ground_at_m'):target={**target,'ground_at_m':selected['ground_at_m']}
        if kind=='tool':
            desired=target.get('ground_at_m') if req.get('test')=='loosens-soil' or req.get('kind')=='own-tool-test' else target['at_m']
            where=target.get('where','world')
            if where not in ('right','left'):
                if where=='world' and _distance(state['pose'],target['at_m'])>2:
                    offer('move',f"Approach {target['body']}",target=target,aim=target['at_m'],stand_off_m=1.2)
                else:offer('acquire',f"Equip {target['body']}" if where=='stowed' else f"Pick up {target['body']}",target=target)
            elif req.get('test')=='study-example':offer('inspect',f"Study held {target['body']}",target=target)
            elif desired:
                distance=_distance(state['pose'],desired)
                least,most=target['reach_m']
                if not least<=distance<=most:
                    offer('move','Step back from the surveyed dry column' if distance<least else
                          'Walk closer to the surveyed dry column',target=target,
                          aim=desired,stand_off_m=(least+most)/2)
                else:offer('use-tool','Use the held tool on surveyed dry soil or sand',target=target,at_m=desired)
            else:blockers.append('No dry soil or sand surveyed near this tool')
        elif kind=='product':
            if _distance(state['pose'],target['at_m'])>2:
                offer('move','Approach your built product',target=target,aim=target['at_m'],stand_off_m=1.2)
            else:offer('pack','Pack your built product in your own bag',target=target)
    kind=req.get('kind')
    if kind=='energy-deposit':
        if state['market'].get('bankable'):offer('bank','Bank 500 J from the measured shared solar battery')
        else:blockers.append('Open the world before banking')
    elif kind=='stock-purchase':
        supplies([{'what':req['substance'],'short_kg':req['remaining_kg']}])
    elif kind=='personal-stock':
        supplies([{'what':req['material'],'short_kg':req['minimum_kg']}])
    elif kind=='funded-ground-tool':
        building({'kind':'ground-tool'})
    elif kind in ('admitted-recipe','funded-box-surface'):
        building(req)
    elif kind=='bag-product':
        body=next((b for b in state['native'].get('bodies',[]) if b['name']==req.get('body')),None)
        if body:target_actions({'body':body['name'],'at_m':body['position_m']},'product')
        else:blockers.append('Your goal product is absent; rebuild it through Recipes')
    elif kind=='own-tool-test':
        row=next((g for g in state['goals']['goals'] if g['id']==state['goals']['next_goal']),{})
        if row.get('target'):target_actions(row['target'],'tool')
        else:blockers.append('Your made tool has no available native action; check Inventory or rebuild through Recipes')
    elif kind=='personal-batch':
        reading=state.get('processing_readiness')
        if reading:
            action=deepcopy(reading['next_action'])
            if action.get('operation')=='find-source':
                # A source location is not a completed rover mining/delivery
                # operation. Retain the single observed shortage honestly.
                action.update(verb='wait',status='Blocked',label=action['label']+' · needs rover input delivery')
            verb,label=action.pop('verb'),action.pop('label')
            offer(verb,label,**action)
        else:blockers.append('No present machine offers a supported batch for this goal')
    elif kind=='personal-test':
        row=next((g for g in state['goals']['goals'] if g['id']==state['goals']['next_goal']),{})
        targets={(t['body'],t.get('machine')):t for t in row.get('targets',[])}
        for skill in state.get('skills',[]):
            if skill.get('known'):continue
            if req.get('technique') and skill['id']!=req['technique']:continue
            if skill.get('unmet'):
                blockers.append(f"{skill['name']} first needs: {', '.join(skill['unmet'])}")
                continue
            for route in skill.get('earned_by',[]):
                for target in route.get('locations',[]):
                    wanted='inspect' if req.get('test')=='study-example' else 'tool/use'
                    if target.get('action')==wanted:
                        targets[(target['body'],target.get('machine'))]=target
        if not targets:
            blockers.extend(m for s in state.get('skills',[]) for m in s.get('world_missing',[]) if
                not req.get('technique') or s['id']==req['technique'])
            blockers.append('No present-world target offers the required supported action')
            building({'kind':'ground-tool'})
        for target in list(targets.values())[:8]:target_actions(target,'tool')
    else:blockers.append('No implemented planner capability for this goal requirement')
    offer('wait','Stop and report current blockers; never invent supplies or success',blockers=list(dict.fromkeys(blockers)))
    return actions


def reference_pick(state,actions):
    # A deterministic capability policy, not a tutorial step-id script. Model
    # mode sees the same offers, requirements, comparisons and observed state.
    for verb in ('continue-process','collect','buy','bank','compare-recipes','select-recipe','acquire','inspect','use-tool',
                 'continue-build','build','pack','power-off','select-process','store-ground','process-input',
                 'power-on','watch-batch','observe','move','select-target','wait'):
        chosen=next((a for a in actions if a['verb']==verb),None)
        if chosen:return chosen['id']
    raise ValueError('The observed catalog has no stop action')


def walking_route(start, aim, stand_off, survey, cancelled=lambda:False):
    """Bounded reported-pose route over native dry columns, not body collision.

    Preflight before moving. Try a straight approach, then A* around water;
    inspect at most 1200 columns and walk at most 64 m at 0.4 m spacing.
    """
    spacing=.4; cache={}
    def floor(x,z):
        at=(round(x,8),round(z,8))
        if at not in cache:
            if cancelled():raise ValueError('Walking was paused')
            if len(cache)>=1200:raise ValueError('Dry route exceeds the 1200-column search budget')
            seen=survey(x,z)
            cache[at]=(seen.get('ground_m') if seen.get('on_the_ground')
                       and (seen.get('water') or {}).get('depth_m',0)<=.2 else None)
        return cache[at]
    sx,sz=start[0],start[2]; ax,az=aim[0],aim[2]
    distance=math.hypot(ax-sx,az-sz)
    if distance>64:raise ValueError('Target exceeds the bounded 64 m walking route')
    dx,dz=((ax-sx)/distance,(az-sz)/distance) if distance>.01 else (1,0)
    tx,tz=ax-dx*stand_off,az-dz*stand_off
    count=max(1,math.ceil(math.hypot(tx-sx,tz-sz)/spacing))
    direct=[]
    for i in range(1,count+1):
        x,z=sx+(tx-sx)*i/count,sz+(tz-sz)*i/count
        y=floor(x,z)
        if y is None:break
        direct.append([x,y,z])
    else:return direct
    def point(cell):return sx+cell[0]*spacing,sz+cell[1]*spacing
    def heuristic(cell):
        x,z=point(cell);return abs(math.hypot(ax-x,az-z)-stand_off)
    queue=[(heuristic((0,0)),0,(0,0))]; costs={(0,0):0}; parents={}
    while queue:
        _,cost,cell=heapq.heappop(queue)
        if cost!=costs[cell]:continue
        if heuristic(cell)<=.24:
            path=[]
            while cell!=(0,0):
                x,z=point(cell);path.append([x,floor(x,z),z]);cell=parents[cell]
            return list(reversed(path))
        for ix,iz in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            nxt=cell[0]+ix,cell[1]+iz;x,z=point(nxt)
            if not min(sx,ax)-6<=x<=max(sx,ax)+6 or not min(sz,az)-6<=z<=max(sz,az)+6:continue
            # Diagonals cannot cut between wet corners.
            if floor(x,z) is None:continue
            if ix and iz and (floor(*point((cell[0]+ix,cell[1]))) is None
                             or floor(*point((cell[0],cell[1]+iz))) is None):continue
            extra=spacing*math.hypot(ix,iz); total=cost+extra
            if total>64 or total>=costs.get(nxt,float('inf')):continue
            parents[nxt]=cell;costs[nxt]=total
            heapq.heappush(queue,(total+heuristic(nxt),total,nxt))
    raise ValueError('No surveyed dry route reaches this target within the search boundary')
