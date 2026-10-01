"""Nearby personal pickup of room goods, paired with a durable room outbox.

The room withdrawal and claim save together. Only saved claims credit SQL;
the SQL receipt and personal credit commit together, so restart/retry cannot
grant a second copy. These are goods ledger packets, not solver bodies.
"""
from __future__ import annotations
import json
import math
import re
import workshop_library
import player_world
import world_access

REQUEST = re.compile(r'[A-Za-z0-9_-]{1,96}')
REACH_M = 2.0
MAX_CLAIMS = 2048


def validate(claims, players):
    if not isinstance(claims, list) or len(claims)>MAX_CLAIMS:
        raise ValueError('Invalid goods collection claims')
    ids=set()
    for r in claims:
        if (not isinstance(r,dict) or not isinstance(r.get('request_id'),str)
            or not REQUEST.fullmatch(r['request_id']) or r['request_id'] in ids
            or r.get('owner') not in players or not isinstance(r.get('pile'),str)
            or not isinstance(r.get('goods'),dict) or not 1<=len(r['goods'])<=16
            or any(not isinstance(k,str) or not k or isinstance(v,bool)
                   or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0
                   for k,v in r['goods'].items())
            or sum(r['goods'].values())>25.000001):
            raise ValueError('Invalid goods collection claim')
        ids.add(r['request_id'])


def settle(app):
    with world_access.state_lock(app):
        _settle(app)


def _settle(app):
    room=getattr(app,'room',None)
    durable=getattr(room,'goods_durable_claims',set())
    for r in getattr(room,'goods_claims',[]) or []:
        if r['request_id'] not in durable: continue
        with workshop_library._connect(app) as db:
            db.execute('CREATE TABLE IF NOT EXISTS world_goods_collections '
                       '(request_id TEXT PRIMARY KEY, owner TEXT NOT NULL, pile TEXT NOT NULL, goods TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            encoded=json.dumps(r['goods'],sort_keys=True)
            old=db.execute('SELECT owner,pile,goods FROM world_goods_collections WHERE request_id=?',
                           (r['request_id'],)).fetchone()
            if old:
                if (old['owner'],old['pile'],old['goods'])!=(r['owner'],r['pile'],encoded):
                    raise ValueError('Goods collection receipt does not match its saved claim')
                continue
            db.execute('INSERT INTO world_goods_collections VALUES (?,?,?,?)',
                       (r['request_id'],r['owner'],r['pile'],encoded))
            for substance,kg in r['goods'].items():
                table,column=('workshop_material_rack','material') if substance in workshop_library.DEFAULT_RACK else ('workshop_goods_rack','substance')
                db.execute(f'INSERT INTO {table}(owner_id,{column},mass_kg,updated_at) '
                           f'VALUES (?,?,?,?) ON CONFLICT(owner_id,{column}) DO UPDATE SET '
                           'mass_kg=mass_kg+excluded.mass_kg,updated_at=excluded.updated_at',
                           (r['owner'],substance,kg,workshop_library._now()))
        # The DB context has committed. Only a newly credited claim emits
        # motion; retries/recovery reads cannot manufacture another transfer.
        goods=getattr(getattr(app,'brains',None),'goods',None)
        pose=(getattr(room,'player_records',{}).get(r['owner']) or {}).get('pose') or {}
        eyes=pose.get('eyes_m')
        if goods is not None and isinstance(eyes,list) and len(eyes)==3:
            goods.activity('collect',r['goods'],{'pile':r['pile']},
                           {'at_m':[eyes[0],eyes[2]]},'player')


def collect(app,owner,body,keep):
    if not getattr(app,'world_id',None) or app.live.session is None:
        raise ValueError('Open a named world before collecting goods')
    request=body.get('request_id'); name=body.get('pile')
    if not isinstance(request,str) or not REQUEST.fullmatch(request):
        raise ValueError('Collect needs a request id')
    if set(body)-{'session','pile','request_id','person'}: raise ValueError('Collect the selected pile with your current position')
    if not isinstance(name,str): raise ValueError('Select an output pile')
    room=app.room
    claims=getattr(room,'goods_claims',None)
    if claims is None: claims=room.goods_claims=[]
    validate(claims,player_world.records(app))
    old=next((r for r in claims if r['request_id']==request),None)
    if old:
        if old['owner']!=owner or old['pile']!=name:
            raise ValueError('This request id belongs to another collection')
        if request not in getattr(room,'goods_durable_claims',set()) and not keep(app,'retry goods collection'):
            raise ValueError('Collection awaits a world save; retry the same request')
        settle(app)
        return {'collected':old['goods'],'pile':name,'repeated':True,'goods':app.brains.goods.holders()}
    if len(claims)>=MAX_CLAIMS: raise ValueError('Collection receipt limit reached')
    goods=app.brains.goods; pile=goods.by_name(name) if goods else None
    if pile is None: raise ValueError('This pile no longer exists')
    if pile.get('rack'): raise ValueError('This legacy rack already credits shared stock; collect from an output pile')
    pose=(player_world.records(app).get(owner) or {}).get('pose') or {}
    eyes=pose.get('eyes_m')
    if not isinstance(eyes,list) or len(eyes)!=3 or math.hypot(eyes[0]-pile['at_m'][0],eyes[2]-pile['at_m'][1])>REACH_M:
        raise ValueError('Get within 2 m of the output to collect it')
    survey=app.live.act({'session':app.live.session.id,'op':'survey','at':pile['at_m']}).get('survey') or {}
    if 'ground_m' not in survey or not 0<=eyes[1]-float(survey['ground_m'])<=3:
        raise ValueError('Stand beside the output on the ground to collect it')
    saved,refused=app.live.snapshot()
    if saved is None: raise ValueError('The world must be saveable before collection: '+str(refused))
    taken=goods.take(*pile['at_m'],25,named=name)['took']
    if not taken: raise ValueError('This output pile is empty')
    claim={'request_id':request,'owner':owner,'pile':name,'goods':taken}
    claims.append(claim)
    if not keep(app,'collect nearby output'):
        raise ValueError('Collection awaits a world save; retry the same request')
    settle(app)
    return {'collected':taken,'pile':name,'repeated':False,'goods':goods.holders()}
