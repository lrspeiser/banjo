"""Durable personal tool receipts from trusted native inspection and replies.

The source is captured by server code, never accepted from a player payload.
An outbox travels with the physical snapshot before journals are updated.
Study proves an inspected example exists; supported ground work proves use.
Neither certifies manufacturing, strength or a new constitutive law.
"""
from __future__ import annotations
import base64
from copy import deepcopy
import hashlib
import json
import logging
import math
import re
import time
from typing import Any
from mcp import progression
import live_session

FIELD = 'player_evidence_pending'
MAX_RECEIPTS = 1024
MAX_BYTES = 2_000_000


def pending_of(app: Any) -> list:
    if not isinstance(getattr(app.room,FIELD,None),list): setattr(app.room,FIELD,[])
    return getattr(app.room,FIELD)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def require_capacity(app):
    if getattr(app,'world_id',None):
        pending=pending_of(app)
        if len(pending)>=MAX_RECEIPTS or len(json.dumps(pending,allow_nan=False))>MAX_BYTES-64_000:
            raise ValueError('Personal learning receipts await saving; retry after saving recovers')


def _construction(value):
    if (not isinstance(value,dict) or set(value)!={'template','one_piece','parts','point'}
        or value['template']!='swing-and-lever' or type(value['one_piece']) is not bool
        or not isinstance(value['parts'],list) or not 1<=len(value['parts'])<=240):
        raise ValueError('Invalid inspected ground-tool construction')
    for part in value['parts']:
        if (not isinstance(part,dict) or set(part)!={'size_m','material','shape'}
            or not isinstance(part['size_m'],list) or len(part['size_m'])!=3
            or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=12 for v in part['size_m'])
            or any(not isinstance(part[k],str) or not part[k] or len(part[k])>120 for k in ('material','shape'))):
            raise ValueError('Invalid inspected sampled component')
    point=value['point']
    if not isinstance(point,dict) or set(point)!={'width_m','thickness_m','angle_deg','length_m'}:
        raise ValueError('Invalid inspected ground point')
    for k,lo,hi in (('width_m',.002,.5),('thickness_m',.002,.5),('angle_deg',5,170),('length_m',.01,1)):
        if type(point[k]) not in (int,float) or not math.isfinite(point[k]) or not lo<=point[k]<=hi:
            raise ValueError('Invalid inspected ground point shape')


def _evaluate(receipt, registry):
    source=receipt['source']
    if receipt['kind']=='ground':
        evidence=progression.evidence_from(source['record'],session_id=receipt['session'],
            spec=source['spec'],registry=registry,at=receipt['at'])
        if evidence is None: raise ValueError('Tool receipt is not a closed supported native result')
    elif receipt['kind']=='study':
        construction=source['construction']
        design=progression.design_of(registry,construction) or progression.own_design_key(construction)
        run=f"{receipt['world']}:{receipt['owner']}:study:{source['tool']}:{source['matter_sha256']}:{_digest(construction)}"
        evidence={'run':run,'at':receipt['at'],'design':design,'object':source['object'],
            'tool':source['tool'],'source':'found-example','test':'study-example','passes':True,
            'action':'inspect held tool','target':{'object':'tool'},
            'result':{'body_id':source['body_id'],'point_id':source['point_id'],'matter_sha256':source['matter_sha256']},
            'models':['native occupied matter','component-frame point'],
            'limitations':['Inspection is not manufacturing, strength or functional certification'],
            'said':f"Studied {source['object']}",'claim':'demonstrated: inspected a whole held example',
            'scope':f'for this inspected construction ({design})'}
    else: raise ValueError('Unknown personal tool receipt kind')
    # Ground event IDs remain unique after native session replacements and
    # include the actual authenticated actor, never the clock request owner.
    evidence['run']=f"{receipt['world']}:{receipt['owner']}:{evidence['run']}"
    evidence['id']='ev-'+hashlib.sha256(evidence['run'].encode()).hexdigest()[:10]
    return evidence


def _checked(receipt, players, registry):
    fields={'owner','world','session','t_s','at','kind','source','evidence'}
    if not isinstance(receipt,dict) or set(receipt)!=fields: raise ValueError('Invalid personal tool receipt')
    if (not isinstance(receipt['owner'],str) or receipt['owner'] not in players
        or not isinstance(receipt['world'],str) or not re.fullmatch('[0-9a-f]{32}',receipt['world'])
        or any(not isinstance(receipt[k],str) or not receipt[k] or len(receipt[k])>120 for k in ('session','at','kind'))
        or type(receipt['t_s']) not in (int,float) or not math.isfinite(receipt['t_s']) or receipt['t_s']<0
        or not isinstance(receipt['source'],dict)):
        raise ValueError('Invalid personal tool source identity')
    source=receipt['source']
    if receipt['kind']=='study':
        if (set(source)!={'construction','tool','object','body_id','point_id','matter_sha256'}
            or not isinstance(source['construction'],dict)
            or any(type(source[k]) is not int or source[k]<=0 for k in ('body_id','point_id'))
            or any(not isinstance(source[k],str) or not source[k] or len(source[k])>120 for k in ('tool','object'))
            or not isinstance(source['matter_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',source['matter_sha256'])):
            raise ValueError('Invalid native tool study source')
        _construction(source['construction'])
    elif receipt['kind']=='ground':
        if set(source)!={'record','spec'} or not isinstance(source['record'],dict) or not isinstance(source['spec'],dict):
            raise ValueError('Invalid native ground source')
        record=source['record']
        if (record.get('open') is not False or record.get('supported') is not True
            or not isinstance(record.get('loosened'),dict)
            or type(record.get('tool_whole')) is not bool):
            raise ValueError('Invalid native closed ground result')
        for k in ('at_s','depth_m','work_j','loosened_kg','closing_speed_m_s','tool_dent_mm'):
            if type(record.get(k)) not in (int,float) or not math.isfinite(record[k]) or record[k]<0:
                raise ValueError('Invalid native ground measured quantity')
        if record['at_s']>receipt['t_s']+1e-9: raise ValueError('Ground receipt precedes its own native event')
        for k in ('sand_m3','soil_m3'):
            if type(record['loosened'].get(k)) not in (int,float) or not math.isfinite(record['loosened'][k]) or record['loosened'][k]<0:
                raise ValueError('Invalid native ground volume')
    expected=_evaluate(receipt,registry)
    if receipt['evidence']!=expected: raise ValueError('Personal tool evidence disagrees with its trusted source')


def validate_pending(value, world, players, registry=None):
    if value is None: return
    try:
        if not isinstance(value,list) or len(value)>MAX_RECEIPTS or len(json.dumps(value,allow_nan=False))>MAX_BYTES:
            raise ValueError('Invalid personal tool outbox')
        registry=registry or progression.Registry()
        for receipt in value:
            _checked(receipt,players,registry)
            if not isinstance(world,dict) or float(world.get('t_s',-1))+1e-9<receipt['t_s']:
                raise ValueError('Personal tool evidence requires its later physical snapshot '
                    f"({receipt['kind']}: source {receipt['t_s']:.12g} s, "
                    f"snapshot {(world or {}).get('t_s',-1):.12g} s)")
    except (KeyError,TypeError,OverflowError) as error:
        raise ValueError('Invalid personal tool outbox source') from error


def queue(app, owner, kind, source, *, session, t_s, registry):
    receipt={'owner':owner,'world':app.world_id,'session':session,'t_s':float(t_s),
        'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'kind':kind,'source':deepcopy(source)}
    receipt['evidence']=_evaluate(receipt,registry)
    _checked(receipt,getattr(app.room,'player_records',{}),registry)
    pending=pending_of(app)
    if any(r['evidence']['id']==receipt['evidence']['id'] for r in pending): return
    if len(pending)>=MAX_RECEIPTS or len(json.dumps(pending+[receipt],allow_nan=False))>MAX_BYTES:
        raise ValueError('Personal tool receipts await saving; retry when saving recovers')
    pending.append(receipt)


def ground(app, owner, session, record, registry):
    spec=session.room_spec
    profile=next((p for p in spec.get('interactions') or [] if p.get('template')=='swing-and-lever'
                  and record.get('tool') in p.get('parts',[])),None)
    if profile is None: return
    names=set(profile['parts'])
    # Historical authored geometry is retained with the native closed result;
    # later edits or dismantling cannot silently change an earlier claim.
    used={'bodies':[deepcopy(b) for b in spec.get('bodies',[]) if b['name'] in names],
          'tool_points':[deepcopy(p) for p in spec.get('tool_points',[]) if p['body'] in names],
          'interactions':[deepcopy(profile)]}
    queue(app,owner,'ground',{'spec':used,'record':record},session=session.id,
          t_s=(session.state or {}).get('t',record['at_s']),registry=registry)


def registry_for_room(room):
    """Bind durable receipts to the playable source graph without rewriting history."""
    if getattr(room,'scene',None)=='new-game':
        import game_materials
        try:
            game_materials.require_spec(room.spec)
        except ValueError:
            pass  # Retained organic saves keep their historical receipt graph.
        else:
            import playable_recipes
            return playable_recipes.registry()
    return progression.Registry()


def _whole_fixed_tool(spec, profile, held, snapshot):
    """Inspect every native constituent, and only live two-way finite fixings.

    A grip may be on a different material group from its cutting point. Neither
    authored adjacency, a hinge nor a broken/one-way fixing proves an assembly.
    """
    import fracture_lab
    names=set(profile['parts'])
    declared=[b for b in spec['bodies'] if b['name'] in names or b.get('join') in names]
    aliases={b['name'] for b in declared} | {b.get('join') or b['name'] for b in declared}
    if not names or not names <= aliases:
        raise ValueError('Study needs every declared tool component')
    groups={}
    for part in declared:
        groups.setdefault(part.get('join') or part['name'],[]).append(part)
    native={b['name']:b for b in snapshot.get('bodies',[]) if b['name'] in groups}
    if held not in groups or set(native)!=set(groups):
        raise ValueError('Study needs the original whole tool and its attached native point')
    matter={}
    for group, parts in groups.items():
        body=native[group]
        expected=fracture_lab.scene_cell_count(parts,spec['cell_m'])
        if (str(body.get('mechanical_model','')).startswith('precise-rigid')
            or type(body.get('body_id')) is not int or body['body_id']<=0
            or not isinstance(body.get('nodes_b64'),str) or not isinstance(body.get('offsets_b64'),str)):
            raise ValueError('Study needs all of the declared sampled matter')
        try:
            nodes=base64.b64decode(body['nodes_b64'],validate=True)
            offsets=base64.b64decode(body['offsets_b64'],validate=True)
        except (ValueError,TypeError) as error:
            raise ValueError('Study needs valid native sampled matter') from error
        if expected<=0 or len(nodes)!=expected*4 or len(offsets)!=expected*24:
            raise ValueError('Study needs all of the declared sampled matter')
        matter[group]={'body_id':body['body_id'],'nodes':body['nodes_b64'],'offsets':body['offsets_b64']}
    point=next((p for p in snapshot.get('tool_points',[]) if p.get('attached') is True
        and p.get('body') in groups and (p.get('grip_body') or p.get('body'))==held),None)
    body=native.get((point or {}).get('body'))
    if (point is None or body is None or point.get('body_id')!=body['body_id']
        or point.get('frame_nodes_b64')!=body['nodes_b64']
        or point.get('frame_offsets_b64')!=body['offsets_b64']):
        raise ValueError('Study needs the original whole tool and its attached native point')
    declared_point=next((p for p in spec.get('tool_points',[]) if p.get('body')==point['body']
        and (p.get('grip_body') or p.get('body'))==held),None)
    if declared_point is None or (declared_point.get('id') is not None and declared_point['id']!=point['id']):
        raise ValueError('Study needs the declared native point on its actual cutting component')
    for field,declared_field,default,scale in (
            ('width_m','width_mm',40.,.001),('thickness_m','thickness_mm',40.,.001),
            ('angle_deg','angle_deg',30.,1.),('length_m','length_mm',150.,.001)):
        actual=point.get(field)
        expected=float(declared_point.get(declared_field,default))*scale
        if type(actual) not in (int,float) or not math.isfinite(actual) or not math.isclose(actual,expected,rel_tol=0,abs_tol=1e-12):
            raise ValueError('Study needs the original declared native point shape')
    edges=[]
    for joint in snapshot.get('joints',[]):
        a,b=joint.get('a'),joint.get('b')
        if (a not in groups or b not in groups or joint.get('attached') is not True
            or joint.get('kind')!='fixing' or joint.get('comes_off_n',0)!=0
            or not isinstance(joint.get('held'),dict)):
            continue
        capacities=[joint.get(k) for k in ('holds_tension_n','holds_shear_n')]
        if all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in capacities):
            edges.append(joint)
    connected={held}
    for _ in groups:
        before=len(connected)
        for joint in edges:
            if joint['a'] in connected or joint['b'] in connected:
                connected.update((joint['a'],joint['b']))
        if len(connected)==before: break
    if connected!=set(groups):
        raise ValueError('Study needs a whole tool joined by attached finite native fixings')
    return point,native[held],{'groups':matter,'point':point,'fixings':edges}


def study(app, owner, name, registry):
    session=app.live.session
    if not getattr(app,'world_id',None) or not owner: return False
    held=live_session.current_hand(session).get('holding')
    profile=next((p for p in app.room.spec.get('interactions',[]) if p.get('template')=='swing-and-lever'
                  and name in p.get('parts',[]) and p.get('tool')==held),None)
    if profile is None: return False
    require_capacity(app)
    snapshot,refused=app.live.snapshot()
    if snapshot is None: raise ValueError('Study waits for the current tool action to finish: '+str(refused))
    point,body,matter=_whole_fixed_tool(app.room.spec,profile,held,snapshot)
    construction=progression.construction_of(app.room.spec,profile)
    source={'construction':construction,'tool':held,'object':profile['object'],
        'body_id':body['body_id'],'point_id':point['id'],
        'matter_sha256':_digest(matter)}
    queue(app,owner,'study',source,session=session.id,t_s=snapshot['t_s'],registry=registry)
    return True


def saved(app,journal_of,registry):
    pending=pending_of(app)
    durable=getattr(app.room,'player_learning_durable_ids',set())
    receipts=[r for r in pending if r['evidence']['id'] in durable]
    validate_pending(receipts,app.room.world_record,app.room.player_records,registry)
    for receipt in receipts:
        try:
            journal=journal_of(app,receipt['owner'])
            journal.add_evidence(receipt['evidence'])
            progression.earn(journal,registry,receipt['at'])
        except (OSError,ValueError):
            logging.getLogger('banjo').exception('Personal tool receipt awaits journal save')
            continue
        pending.remove(receipt)
