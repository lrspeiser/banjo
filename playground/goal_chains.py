"""Bounded declarative checklists over durable game evidence, never awards.

New chains may compose the supported predicates. New predicate kinds need
server implementation and tests; names, client claims and navigation are not
evidence. Progress is personal and retained once a source receipt is saved.
"""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
from mcp import progression, workshop
import workshop_library


@lru_cache(maxsize=1)
def definitions():
    raw = json.loads((Path(__file__).resolve().parents[1]/'progression/goals.json').read_text(encoding='utf-8'))
    if raw.get('format') != 'banjo.goal-chains.v1' or not isinstance(raw.get('chains'),list) or not 1 <= len(raw['chains']) <= 32:
        raise ValueError('Invalid bounded goal catalog')
    chains = {}
    registry=progression.Registry()
    for chain in raw['chains']:
        if (set(chain) != {'id','title','after','limits','steps'} or chain['id'] in chains or chain['id']=='first-camp-v1'
            or not isinstance(chain['steps'],list) or not 1 <= len(chain['steps']) <= 16
            or not isinstance(chain['after'],str) or len(chain['after'])>800
            or any(not isinstance(chain[k],str) or not chain[k] or len(chain[k])>800 for k in ('id','title','limits'))):
            raise ValueError('Invalid goal chain')
        seen = set()
        for step in chain['steps']:
            if (set(step) != {'id','title','unit','target','predicate','guide'} or step['id'] in seen
                or type(step['target']) is not int or step['target'] != 1
                or any(not isinstance(step[k],str) or not step[k] or len(step[k])>120 for k in ('id','title','unit'))):
                raise ValueError('Goal steps require unique ids and one source receipt')
            seen.add(step['id'])
            p = step['predicate']; kind = p.get('kind')
            if kind == 'personal-test':
                if (set(p)-{'kind','test','source','positive','technique'}
                    or p.get('test') not in ('study-example','loosens-soil') or p.get('source') != 'found-example'
                    or p.get('technique') and p['technique'] not in registry.techniques):
                    raise ValueError('Unsupported personal test predicate')
                if p.get('positive') not in (None,'loosened_m3'):
                    raise ValueError('Unsupported measured quantity')
            elif kind == 'funded-box-surface':
                if set(p) != {'kind','minimum_area_m2'} or type(p['minimum_area_m2']) not in (int,float) or not .01 <= p['minimum_area_m2'] <= 4:
                    raise ValueError('Invalid supported surface area')
            elif kind == 'personal-stock':
                import game_materials
                if (set(p) != {'kind','material','minimum_kg'} or not game_materials.allowed(p['material'])
                    or type(p['minimum_kg']) not in (int,float) or not .01 <= p['minimum_kg'] <= 25):
                    raise ValueError('Invalid personal opening stock')
            elif kind in ('funded-ground-tool','own-tool-test','own-light-used','own-solar-collected'):
                if set(p) != {'kind'}: raise ValueError('Invalid funded tool predicate')
            elif kind != 'personal-batch' or set(p) != {'kind'}:
                raise ValueError('Unknown goal predicate; implement its evaluator first')
            guide=step['guide']
            if (set(guide)-{'where','screen','steps','recipe'} or not {'where','screen','steps'} <= set(guide)
                or guide['screen'] not in ('world','skills','recipes','inventory','market')
                or not isinstance(guide['steps'],list) or not 1 <= len(guide['steps']) <= 6
                or any(not isinstance(s,str) or not s or len(s)>800 for s in guide['steps'])):
                raise ValueError('Invalid goal navigation guide')
        chains[chain['id']] = chain
    for ident in chains:
        seen=set(); current=ident
        while current not in ('first-camp-v1',''):
            if current in seen or current not in chains: raise ValueError('Goal prerequisite is missing or cyclic')
            seen.add(current);current=chains[current]['after']
    ordered={}
    while len(ordered)<len(chains):
        for ident,chain in chains.items():
            if ident not in ordered and (chain['after'] in ('first-camp-v1','') or chain['after'] in ordered):
                ordered[ident]=chain
    return ordered


def completed(app,owner,ident):
    import starter_goals
    ids=([s[0] for s in starter_goals.STEPS] if ident==starter_goals.CHAIN else
         [s['id'] for s in definitions()[ident]['steps']])
    with workshop_library._connect(app) as db:
        done={r['goal_id'] for r in db.execute(
            'SELECT goal_id FROM starter_goal_progress WHERE owner_id=? AND chain_id=?',(owner,ident))}
    return set(ids)<=done


def work_table_recipe():
    import playable_recipes
    return playable_recipes.recipe('bench',design_id='starter-work-table')


def exact_furniture_recipe(kind, design_id):
    """A catalog piece of furniture built from exact parts, as the Work table
    is: its thin parts (a shelf's 18 mm sides, a chair's back posts) are under
    the 40 mm Workshop cell and cannot be drawn in cells without being
    redrawn away from what they join."""
    import playable_recipes
    return playable_recipes.recipe(kind,design_id=design_id)


def first_tool_recipe():
    import playable_recipes
    return playable_recipes.recipe('field-pick',design_id='starter-personal-pick')


def camp_light_recipe():
    """Small useful variant; its output charge is included in paid manufacture."""
    from mcp import workshop_components
    source={'kind':'mine-lamp','design_id':'starter-camp-light','parameters':{
        'globe_m':.07,'bracket_m':.08,'foot_m':.16,'material':'iron',
        'watts':5.,'efficacy_lm_w':120.}}
    design,overrides=workshop_components.design_from_spec(source)
    # Genuine iron geometry, not an oak-sized solid foot renamed to metal.
    overrides['foot'].update(size_m=[.16,.005,.16],center_m=[0.,.0025,0.])
    overrides['globe bracket'].update(size_m=[.02,.08,.02],center_m=[0.,.045,0.])
    overrides['globe'].update(center_m=[0.,.12,0.])
    overrides['@machines']={
        'stores':[{'name':'camp battery','in':'foot','capacity_j':3500.,
                   'charge_j':3000.,'voltage_v':24.,'max_power_w':20.}],
        'lamps':[{'name':'camp light','on':'globe','store':'camp battery',
                  'watts':5.,'efficacy_lm_w':120.,'on_at_first':False}]}
    return {**source,'parameters':dict(design.parameters),'component_overrides':overrides}


def camp_solar_recipe():
    """A one-panel collector a new player can afford, ahead of the yard array.

    Geometry, panel area, battery capacity and output rating are all reduced
    together: 0.24 m2 of glass at 20% gives about 48 W in full sun, into a
    50 Wh battery rated at 60 W, so it asks for 1.8 kg of copper, not 200.
    It starts empty and banks its surplus like the full array; nothing about
    the solar law is changed for it.
    """
    from mcp import workshop
    design=workshop.assemble('solar-array',design_id='starter-camp-solar',parameters={
        'panels':1,'panel_w_m':.6,'panel_d_m':.4,'frame_height_m':.35,
        'capacity_j':1.8e5,'charge_j':0.,'max_power_w':60.,'efficiency':.2,'material':'iron',
        'panel_thickness_m':.004})
    overrides=deepcopy(design.lineage.get('component_overrides') or {})
    overrides['frame'].update(size_m=[1.22,.0035,.52],center_m=[0.,.34825,0.])
    for part in design.parts:
        if part.name.startswith('leg-'):
            overrides[part.name].update(size_m=[.01,.3465,.01],
                center_m=[part.center_m[0],.17325,part.center_m[2]])
    overrides['battery'].update(size_m=[.05,.005,.05],center_m=[.3,.3525,0.])
    return {'kind':design.kind,'design_id':design.design_id,'parameters':dict(design.parameters),
            'component_overrides':overrides}


def funded_tools(saved, owner):
    """Saved paid native admission plus an actual installed ground-tool profile.

    A client name, recipe annotation or another builder's receipt grants nothing.
    Whole/use capability still has to pass the ordinary native use controller.
    """
    spec=saved.get('spec') or {}
    present={b['name'] for b in (saved.get('world') or {}).get('bodies',[])}
    authored={b['name'] for b in spec.get('bodies',[])}
    profiles=[p for p in spec.get('interactions',[]) if p.get('template')=='swing-and-lever']
    tools=[]
    for receipt in saved.get('workshop_installs',[]):
        if (receipt.get('status')!='installed' or receipt.get('owner_id')!=owner
            or not receipt.get('resources_charged') or not receipt.get('engine_grid_verified')): continue
        roots=set(receipt.get('root_bodies') or [receipt.get('root_body')])
        for profile in profiles:
            # Monolithic lattice parts share one native body; a component's
            # authored name need not be an additional native body name.
            if (profile.get('tool') not in roots or profile['tool'] not in present
                or not set(profile.get('parts') or []) <= authored): continue
            tools.append({'request_id':receipt['request_id'],'body':profile['tool'],
                'parts':list(profile.get('parts') or []),'physics_hash':receipt['matter_physics_hash']})
    return tools


def _surface(saved, owner, area):
    """A funded native-admitted box face, not an arbitrary surface annotation.

    This initial predicate admits precise rigid boxes only. It checks the
    saved point against the actual saved box face; lattice/curved/tipped
    surfaces require a separate measured support predicate before admission.
    """
    spec=saved.get('spec') or {}
    native={b['name']:b for b in (saved.get('world') or {}).get('bodies',[])}
    bodies={b['name']:b for b in spec.get('precise_rigid_bodies',[])}
    points={r['body']:r['points'] for r in spec.get('interaction_points',[])}
    for receipt in reversed(saved.get('workshop_installs',[])):
        root=receipt.get('root_body'); body=bodies.get(root); live=native.get(root)
        if (receipt.get('status')!='installed' or receipt.get('owner_id')!=owner
            or not receipt.get('resources_charged') or not receipt.get('native_precise_geometry_verified')
            or not body or not live or live.get('parked') or live.get('fragment')): continue
        # Native identity/body presence is checked in the same durably saved
        # document as the admission receipt and geometry.
        q=live.get('orientation_wxyz',[1,0,0,0])
        if 1-2*(q[1]*q[1]+q[3]*q[3]) < math.cos(math.radians(15)): continue
        for point in points.get(root,[]):
            if point['kind']!='surface': continue
            at=point['position_m']; size=point['size_m']
            angle=math.radians(point.get('yaw_deg',0))
            footprint=[abs(math.cos(angle))*size[0]+abs(math.sin(angle))*size[2],
                       abs(math.sin(angle))*size[0]+abs(math.cos(angle))*size[2]]
            for part in body['parts']:
                if part.get('shape','box')!='box' or part.get('rotation_wxyz',[1,0,0,0]) != [1,0,0,0]: continue
                d=part['dimensions_m']; c=part['center_local_m']
                if (abs(at[1]-(c[1]+d[1]/2)) <= 1e-7
                    and abs(at[0]-c[0])+footprint[0]/2 <= d[0]/2+1e-7
                    and abs(at[2]-c[2])+footprint[1]/2 <= d[2]/2+1e-7
                    and size[0]*size[2]>=area):
                    return {'request_id':receipt['request_id'],'body':root,
                        'physics_hash':receipt['matter_physics_hash'],'surface':point['id'],
                        'area_m2':size[0]*size[2],'saved_t_s':saved['world']['t_s']}
    return None


def _owned_roots(saved, owner):
    """Native bodies of this player's paid, admitted installations."""
    roots=set()
    for receipt in saved.get('workshop_installs',[]):
        if (receipt.get('status')!='installed' or receipt.get('owner_id')!=owner
            or not receipt.get('resources_charged')): continue
        roots|=set(receipt.get('root_bodies') or [receipt.get('root_body')])
        roots|=set((receipt.get('component_to_body') or {}).values())
    return roots-{None}


def _light_used(saved, owner):
    """An own installed lamp that has actually drawn energy to give light.

    The engine counts what each lamp draws (drawn_j); a lamp that never lit
    has drawn nothing. Placing it, or switching it on with an empty battery,
    is not a lit camp."""
    world=saved.get('world') or {}; roots=_owned_roots(saved,owner)
    for lamp in world.get('lamps',[]):
        if lamp.get('body') in roots and float(lamp.get('drawn_j') or 0)>0:
            return {'body':lamp['body'],'lamp':lamp.get('name'),'drawn_j':float(lamp['drawn_j']),
                    'saved_t_s':world.get('t_s')}
    return None


def _solar_collected(saved, owner):
    """An own installed solar panel whose battery has received energy.

    taken_j is what a store has taken in from its panels since it was made
    (LiveEnergyStore); given_j is what it has given out, which a battery that
    only banks or lights can do without the sun ever touching it."""
    world=saved.get('world') or {}; roots=_owned_roots(saved,owner)
    panelled={p.get('body') for p in world.get('solar_panels',[]) if p.get('body') in roots}
    for store in world.get('energy_stores',[]):
        if store.get('body') in panelled and float(store.get('taken_j') or 0)>0:
            return {'body':store['body'],'store':store.get('name'),'taken_j':float(store['taken_j']),
                    'saved_t_s':world.get('t_s')}
    return None


def own_devices(app, saved, owner, kind):
    """This player's own installed lamps (own-light-used) or panels
    (own-solar-collected), as the running room has them now."""
    state=getattr(getattr(app.live,'session',None),'state',None) or {}
    roots=_owned_roots(saved,owner)
    bodies={b['name']:b for b in state.get('bodies',[])}
    machines=state.get('machines') or {}
    stores={s.get('id'):s for s in machines.get('stores',[])}
    rows=[]
    if kind=='own-light-used':
        for lamp in machines.get('lamps',[]):
            body=bodies.get(lamp.get('body'))
            if lamp.get('body') in roots and body and not body.get('parked'):
                store=stores.get(lamp.get('store'),{})
                rows.append({'body':lamp['body'],'at_m':body['position_m'],'on':bool(lamp.get('on')),
                    'lit':bool(lamp.get('lit')),'charge_j':store.get('charge_j')})
    else:
        sun=state.get('sun') or {}
        for panel in machines.get('panels',[]) or machines.get('solar_panels',[]):
            body=bodies.get(panel.get('body'))
            if panel.get('body') in roots and body and not body.get('parked'):
                rows.append({'body':panel['body'],'at_m':body['position_m'],
                    'daylight':float(sun.get('elevation_deg',1))>0})
    return rows


def evaluate(predicate, journal, saved, owner, world, registry):
    if predicate['kind']=='own-light-used':
        return _light_used(saved,owner)
    if predicate['kind']=='own-solar-collected':
        return _solar_collected(saved,owner)
    if predicate['kind']=='funded-box-surface':
        return _surface(saved,owner,predicate['minimum_area_m2'])
    if predicate['kind']=='funded-ground-tool':
        return next(iter(reversed(funded_tools(saved,owner))),None)
    if predicate['kind']=='personal-stock':
        raise ValueError('Personal stock requires an authenticated inventory read')
    tools=funded_tools(saved,owner) if predicate['kind']=='own-tool-test' else []
    for e in journal.copy()['evidence'].values():
        if e.get('passes') is not True or not e.get('run','').startswith(world+':'): continue
        if predicate['kind']=='own-tool-test':
            tool=next((t for t in tools if e.get('tool') in t['parts']),None)
            if (not tool or not e['run'].startswith(world+':'+owner+':')
                or e.get('source')!='found-example' or e.get('test')!='loosens-soil'
                or (e.get('result') or {}).get('loosened_m3',0)<=0
                or ((e.get('tool_condition') or {}).get('after') or {}).get('whole') is not True): continue
            return {**deepcopy(tool),'evidence_id':e['id'],'result':deepcopy(e['result'])}
        elif predicate['kind']=='personal-test':
            if not e['run'].startswith(world+':'+owner+':') or e.get('source')!=predicate['source'] or e.get('test')!=predicate['test']: continue
            if predicate.get('technique') and predicate['technique'] not in journal.knows(): continue
            if predicate.get('positive') and not (e.get('result') or {}).get(predicate['positive'],0)>0: continue
        else:
            if (e.get('source')!='watched' or (e.get('observer') or {}).get('player')!=owner
                or 'machine_goods recipe ledger' not in e.get('models',[]) or (e.get('result') or {}).get('made_kg',0)<=0): continue
            known=next((d for d in registry.designs.values() if f"{d['id']}@{d['revision']}"==e.get('design')),None)
            checked=progression.batch_design(registry,(known or {}).get('machine',{}).get('recipe',''))
            if not checked or checked[1]['id']!=e.get('test'): continue
        return {'evidence_id':e['id'],'design':e['design'],'test':e['test'],'result':deepcopy(e['result'])}
    return None


def view(app,owner,ident):
    # Resolve explicit owner even when an AI viewer requests another journal.
    import starter_goals
    chain=definitions().get(ident)
    if chain is None: raise ValueError('Unknown goal chain')
    journal=app.journal_for(owner); reg=app.registry()
    saved=app.store.read_record(app.room.scene)
    token=workshop_library.REQUEST_OWNER.set(owner)
    try: personal={r['material']:r['personal_kg'] for r in workshop_library.rack(app)['materials']}
    finally: workshop_library.REQUEST_OWNER.reset(token)
    with workshop_library._connect(app) as db:
        starter_goals._schema(db)
        done={r['goal_id']:json.loads(r['evidence_json']) for r in db.execute(
            'SELECT goal_id,evidence_json FROM starter_goal_progress WHERE owner_id=? AND chain_id=?',(owner,ident))}
        for step in chain['steps']:
            if step['id'] in done: continue
            predicate=step['predicate']
            if predicate['kind']=='personal-stock':
                material=predicate['material']; kg=personal.get(material,0)
                receipt=({'material':material,'personal_kg':kg} if kg+1e-9>=predicate['minimum_kg'] else
                         next(iter(reversed(funded_tools(saved,owner))),None))
            else: receipt=evaluate(predicate,journal,saved,owner,app.world_id,reg)
            if receipt:
                db.execute('INSERT OR IGNORE INTO starter_goal_progress VALUES (?,?,?,?,?)',
                    (owner,ident,step['id'],json.dumps(receipt),workshop_library._now()))
                done[step['id']]=receipt
    rows=[{k:deepcopy(s[k]) for k in ('id','title','unit','target','guide')} |
        {'requirement':deepcopy(s['predicate'])} |
        {'value':int(s['id'] in done),'complete':s['id'] in done,'evidence':done.get(s['id'])}
        for s in chain['steps']]
    tools=funded_tools(saved,owner)
    product=next((t['body'] for t in reversed(tools)),None)
    for row in rows:
        if row['requirement']['kind']=='personal-test' and not row['complete']:
            import learning_routes
            row['targets']=[target for profile in app.room.spec.get('interactions',[])
                if profile.get('template')=='swing-and-lever'
                if (target:=learning_routes.tool_location(app,owner,profile['tool']))
                if row['requirement']['test']=='study-example' or target.get('ground_at_m')]
        if row['requirement']['kind'] in ('own-light-used','own-solar-collected') and not row['complete']:
            row['targets']=own_devices(app,saved,owner,row['requirement']['kind'])
        if row['requirement']['kind']=='own-tool-test':
            row['guide']['body']=product
            if not row['complete'] and product:
                import learning_routes
                row['target']=learning_routes.tool_location(app,owner,product)
        if row['requirement']['kind']=='personal-stock':
            goods=getattr(getattr(app,'brains',None),'goods',None)
            piles=goods.holders()['stockpiles'] if goods else []
            material=row['requirement']['material']
            pose=((saved.get('players') or {}).get(owner) or {}).get('pose') or {}
            eye=pose.get('eyes_m') or [0,1.62,3]
            available=[p for p in piles if not p.get('rack') and p['holds_kg'].get(material,0)>0]
            available.sort(key=lambda p:math.hypot(p['at_m'][0]-eye[0],p['at_m'][1]-eye[2]))
            if not getattr(app.live,'session',None) or app.live_holder!='world':
                row['guide'].update(screen='world',where='World')
                row['guide']['steps']=['Open your saved World to read its current loose mineral and metal supplies.',
                    'Then follow the measured material source shown by your next action.']
            elif available:
                row['guide'].update(resource=available[0]['name'],available_kg=available[0]['holds_kg'][material])
                row['guide']['steps'][0]=f"Find {available[0]['name']} in World; it contains {available[0]['holds_kg'][material]:g} kg {material}."
            else:
                row['guide'].update(screen='market',where='Market')
                row['guide']['steps']=[f'Loose {material} piles are empty. Use stock already in Inventory or the workbench; Market is an alternative supply.',
                    'If Market is also empty, wait for its finite trader restock. No material is created by this checklist.']
    return {'schema':'banjo.starter-goals.v1','chain_id':ident,'title':chain['title'],
        'goals':rows,'next_goal':next((r['id'] for r in rows if not r['complete']),None),
        'complete':all(r['complete'] for r in rows),'limits':chain['limits'],
        'follow_up':'Use Skills to find the next supported experiment.',
        'recipe':first_tool_recipe() if ident=='first-tool-v1' else work_table_recipe(),
        'product_body':product,
        'session':getattr(getattr(app.live,'session',None),'id',None)}
