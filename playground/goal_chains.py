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
                if (set(p) != {'kind','material','minimum_kg'} or p['material'] != 'oak'
                    or type(p['minimum_kg']) not in (int,float) or not .01 <= p['minimum_kg'] <= 25):
                    raise ValueError('Invalid personal opening stock')
            elif kind in ('funded-ground-tool','own-tool-test'):
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
    design=workshop.assemble('bench',design_id='starter-work-table',parameters={
        'width_m':.48,'depth_m':.32,'height_m':.50,'top_profile':'square',
        'leg_section_m':.04,'top_thickness_m':.04,'aprons':0,'stretchers':0,
        'splay_deg':0,'material':'oak'})
    design.parameters['primary_use']={'label':'Place work surface','steps':[{'do':'place'}]}
    return {'kind':design.kind,'design_id':design.design_id,'parameters':dict(design.parameters),
        'component_overrides':{p.name:{'mechanics':{'model':'rigid'}} for p in design.parts}}


def first_tool_recipe():
    design=workshop.assemble('field-pick',design_id='starter-personal-pick')
    return {'kind':design.kind,'design_id':design.design_id,
            'parameters':dict(design.parameters),'component_overrides':{}}


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


def evaluate(predicate, journal, saved, owner, world, registry):
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
                row['guide']['steps']=['Open your saved World to read its current loose wood supplies.',
                    'Then follow the measured material source shown by your next action.']
            elif available:
                row['guide'].update(resource=available[0]['name'],available_kg=available[0]['holds_kg'][material])
                row['guide']['steps'][0]=f"Find {available[0]['name']} in World; it contains {available[0]['holds_kg'][material]:g} kg {material}."
            else:
                row['guide'].update(screen='market',where='Market')
                row['guide']['steps']=['Loose wood piles are empty. Use wood already in Inventory or the workbench; Market is an alternative supply.',
                    'If Market is also empty, wait for its finite trader restock. No wood is created by this checklist.']
    return {'schema':'banjo.starter-goals.v1','chain_id':ident,'title':chain['title'],
        'goals':rows,'next_goal':next((r['id'] for r in rows if not r['complete']),None),
        'complete':all(r['complete'] for r in rows),'limits':chain['limits'],
        'follow_up':'Use Skills to find the next supported experiment.',
        'recipe':first_tool_recipe() if ident=='first-tool-v1' else work_table_recipe(),
        'product_body':product,
        'session':getattr(getattr(app.live,'session',None),'id',None)}
