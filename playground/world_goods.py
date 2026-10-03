"""Nearby personal pickup of room goods, paired with a durable room outbox.

The room withdrawal and claim save together. Only saved claims credit SQL;
the SQL receipt and personal credit commit together, so restart/retry cannot
grant a second copy. These are goods ledger packets, not solver bodies.
"""
from __future__ import annotations
import json
import math
import re
from copy import deepcopy
import workshop_library
import player_world
import world_access

REQUEST = re.compile(r'[A-Za-z0-9_-]{1,96}')
REACH_M = 2.0
MAX_CLAIMS = 2048
MAX_DELIVERY_KG = 25.


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


def validate_raw_deliveries(state, claims):
    records=(state or {}).get('raw_input_deliveries',{})
    raw={r['request_id']:r for r in claims if 'raw_lot_id' in r}
    if set(raw)!=set(records): raise ValueError('Raw inputs require matching receiving receipts')
    for ident,record in records.items():
        claim=raw[ident]
        if (claim['owner']!=record['owner'] or claim['pile']!=record['pile']
                or claim['raw_lot_id']!=record['lot_id']
                or claim['goods']!={v['substance']:v['mass_kg'] for v in record['packet']['contents']}):
            raise ValueError('Raw input receipt changed its source or destination')


def _settle(app):
    room=getattr(app,'room',None)
    if room is None:return  # A standalone authoring catalog has no room outbox.
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
                           {'player':r['owner'],'point_m':[eyes[0],eyes[1]-.3,eyes[2]]},'player')
    _settle_deliveries(app)


def collect(app,owner,body,keep):
    if not getattr(app,'world_id',None) or app.live.session is None:
        raise ValueError('Open a named world before collecting goods')
    request=body.get('request_id'); name=body.get('pile')
    if not isinstance(request,str) or not REQUEST.fullmatch(request):
        raise ValueError('Collect needs a request id')
    if set(body)-{'session','pile','request_id','person','automatic'}: raise ValueError('Collect the selected pile with your current position')
    if not isinstance(body.get('automatic',False),bool): raise ValueError('Automatic collection must be true or false')
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
    if body.get('automatic'):
        routines=[b.routine for b in app.brains.brains.values()]
        if (not any(r.output==name for r in routines) or any(r.intake==name for r in routines)):
            raise ValueError('Only finished machine outputs collect automatically; inputs stay in their hopper')
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


def _delivery_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS world_goods_deliveries '
               '(scene TEXT NOT NULL, request_id TEXT NOT NULL, owner TEXT NOT NULL, '
               'pile TEXT NOT NULL, goods TEXT NOT NULL, '
               "status TEXT NOT NULL CHECK(status IN ('reserved','applied','released')), "
               'PRIMARY KEY(scene,request_id))')


def pending_deliveries(app, owner):
    room=getattr(app,'room',None)
    if room is None:return []
    received={r['request_id'] for r in (getattr(room,'goods_deliveries',[]) or [])}
    with workshop_library._connect(app) as db:
        _delivery_schema(db)
        return [{'request_id':r['request_id'],'pile':r['pile'],'goods':json.loads(r['goods']),
                 'received':r['request_id'] in received}
                for r in db.execute("SELECT * FROM world_goods_deliveries WHERE scene=? AND owner=? AND status='reserved'",
                                    (room.scene,owner))]


def _settle_deliveries(app):
    room=app.room
    claims=[r for r in (getattr(room,'goods_deliveries',[]) or [])
            if r['request_id'] in getattr(room,'goods_durable_deliveries',set()) and 'raw_lot_id' not in r]
    if not claims:return
    with workshop_library._connect(app) as db:
        _delivery_schema(db)
        db.execute('BEGIN IMMEDIATE')
        for claim in claims:
            old=db.execute('SELECT * FROM world_goods_deliveries WHERE scene=? AND request_id=?',
                           (room.scene,claim['request_id'])).fetchone()
            if (old is None or old['owner']!=claim['owner'] or old['pile']!=claim['pile']
                    or json.loads(old['goods'])!=claim['goods'] or old['status']=='released'):
                raise ValueError('Saved machine delivery has no matching reserved source')
            if old['status']=='reserved':
                db.execute("UPDATE world_goods_deliveries SET status='applied' WHERE scene=? AND request_id=?",
                           (room.scene,claim['request_id']))


def _delivery_inputs(app, pile):
    goods=app.brains.goods
    source=goods.by_name(pile)
    if source is None or source.get('rack'):raise ValueError('Select a machine input hopper')
    accepted=set()
    for brain in app.brains.brains.values():
        routine=brain.routine
        if routine is not None and routine.intake==pile:
            recipe=goods.recipe(routine.recipe)
            accepted.update((recipe or {}).get('in',{}))
    if not accepted:raise ValueError('This pile is not a supported machine input')
    return source,accepted


def _personal_meter(db, owner, substance):
    table,column=('workshop_material_rack','material') if substance in workshop_library.DEFAULT_RACK else ('workshop_goods_rack','substance')
    row=db.execute(f'SELECT mass_kg FROM {table} WHERE owner_id=? AND {column}=?',(owner,substance)).fetchone()
    return table,column,float(row['mass_kg']) if row else 0.


def delivery(app, owner, body, keep):
    """SQL source escrow before the paired hopper/receipt checkpoint.

    A failed room save retains the source reservation. A restart restores the
    last hopper and retries the same reservation; it never debits a second copy.
    """
    if not getattr(app,'world_id',None) or app.live.session is None:
        raise ValueError('Open a named world before delivering materials')
    if owner not in player_world.records(app):raise ValueError('Join this world before delivering materials')
    with world_access.gate(app).enter(exclusive=True),world_access.state_lock(app):
        return _delivery(app,owner,body,keep)


def input_readiness(app,owner,pile,accepted):
    """Shared current input facts for Inventory and process guidance; no delivery."""
    room=app.room
    with workshop_library._connect(app) as db:
        choices=[{'substance':s,'mass_kg':_personal_meter(db,owner,s)[2]} for s in sorted(accepted)]
    from mcp import fabrication
    state=getattr(room,'fabrication_record',None) or {}
    import inventory_room
    carried=inventory_room._carried(app,owner)
    stored=[]
    for lot,items in fabrication.raw_inventory(state).items():
        owned=state.get('raw_lot_ownership',{}).get(lot,{}).get('owner','')
        if owned and owned!=owner:continue
        stored.extend({'lot_id':lot,**v,'pool':'personal' if owned else 'shared'}
            for v in items if v['substance'] in accepted and v['mass_kg']>=.000001)
    for row in choices:
        substance=row['substance']
        row['hopper_kg']=float((pile.get('holds') or {}).get(substance,0))
        row['stored_kg']=sum(r['mass_kg'] for r in stored if r['substance']==substance)
        row['stored_personal_kg']=sum(r['mass_kg'] for r in stored
            if r['substance']==substance and r['pool']=='personal')
        row['carried_kg']=float(carried.get(substance+'_kg',0)) if substance in fabrication.GROUND_DENSITIES else 0.
        row['carried_m3']=float(carried.get(substance+'_m3',0)) if substance in fabrication.GROUND_DENSITIES else 0.
        row['sources']=[{'name':d['name'],'at_m':d['at_m'],
            'left_kg':app.brains.goods.reserve_kg(d)}
            for d in app.brains.goods.deposits if d['substance']==substance]
        row['next']=('processing' if row['hopper_kg']>=.000001 else
            'load_stored' if row['stored_kg']>=.000001 else
            'load_inventory' if row['mass_kg']>=.000001 else
            'store_ground' if row['carried_kg']>=.000001 else
            'gather_ground' if substance in fabrication.GROUND_DENSITIES else
            'mine_source' if any(d['left_kg']>0 for d in row['sources']) else
            'source_exhausted' if row['sources'] else 'find_supply')
    return {'pile':pile['name'],'inputs':choices,'stored':stored,'raw_revision':state.get('revision'),
            'pending':pending_deliveries(app,owner)}


def _delivery(app, owner, body, keep):
    action=body.get('action','deliver')
    if action not in ('view','deliver','release'):raise ValueError('Unknown material delivery action')
    if set(body)-{'session','pile','request_id','person','substance','mass_kg','action','lot_id','revision'}:
        raise ValueError('Deliver a selected Inventory material to a machine input')
    room=app.room
    claims=getattr(room,'goods_deliveries',None)
    if claims is None:claims=room.goods_deliveries=[]
    validate(claims,player_world.records(app))
    if action=='view':
        pile,accepted=_delivery_inputs(app,body.get('pile'))
        return input_readiness(app,owner,pile,accepted)
    request=body.get('request_id')
    if not isinstance(request,str) or not REQUEST.fullmatch(request):raise ValueError('Delivery needs a request id')
    with workshop_library._connect(app) as db:
        _delivery_schema(db)
        old=db.execute('SELECT * FROM world_goods_deliveries WHERE scene=? AND request_id=?',
                       (room.scene,request)).fetchone()
    claim=next((r for r in claims if r['request_id']==request),None)
    if old is not None and old['owner']!=owner:raise ValueError('This delivery belongs to another player')
    if action=='release':
        if old is None:raise ValueError('This delivery reservation does not exist')
        # Read durable evidence, including the save-succeeded/ack-lost case.
        durable=app.store.read_record(room.scene).get('goods_deliveries',[])
        if claim is not None or any(r['request_id']==request for r in durable) or old['status']=='applied':
            raise ValueError('Materials already entered the hopper; finish the delivery save instead')
        with workshop_library._connect(app) as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT status FROM world_goods_deliveries WHERE scene=? AND request_id=?',
                               (room.scene,request)).fetchone()['status']
            if current=='reserved':
                for substance,mass in json.loads(old['goods']).items():
                    table,column,_=_personal_meter(db,owner,substance)
                    db.execute(f'UPDATE {table} SET mass_kg=mass_kg+? WHERE owner_id=? AND {column}=?',
                               (mass,owner,substance))
                db.execute("UPDATE world_goods_deliveries SET status='released' WHERE scene=? AND request_id=?",
                           (room.scene,request))
        return {'released':True,'repeated':current=='released'}
    substance=body.get('substance'); mass=body.get('mass_kg')
    if (not isinstance(substance,str) or isinstance(mass,bool) or not isinstance(mass,(int,float))
            or not math.isfinite(mass) or not .000001<=mass<=MAX_DELIVERY_KG
            or abs(mass*1e6-round(mass*1e6))>1e-6):
        raise ValueError('Deliver 0.000001 to 25 kg in whole micrograms')
    packet={substance:round(float(mass),6)}
    encoded=json.dumps(packet,sort_keys=True)
    if 'lot_id' in body:
        if old is not None: raise ValueError('This request id already names an Inventory delivery')
        return _deliver_raw(app,owner,body,packet)
    if old is not None and (old['pile']!=body.get('pile') or old['goods']!=encoded):
        raise ValueError('This request id already names another delivery')
    if old is not None and old['status']=='released':raise ValueError('This reservation was returned; use a new request id')
    if claim is not None:
        if old is None or claim['owner']!=owner or claim['pile']!=body.get('pile') or claim['goods']!=packet:
            raise ValueError('Delivery receipt does not match its reserved source')
        if request not in getattr(room,'goods_durable_deliveries',set()) and not keep(app,'retry material delivery'):
            raise ValueError('Delivery awaits a world save; retry the same request')
        _settle_deliveries(app)
        return {'delivered':packet,'pile':claim['pile'],'repeated':True,'goods':app.brains.goods.holders()}
    if old is not None and old['status']=='applied':raise ValueError('Saved delivery receipt is missing; refusing another copy')
    pile,accepted=_delivery_inputs(app,body.get('pile'))
    if substance not in accepted:raise ValueError('This machine input does not accept '+substance)
    eyes=(player_world.records(app)[owner].get('pose') or {}).get('eyes_m')
    if not isinstance(eyes,list) or len(eyes)!=3 or math.hypot(eyes[0]-pile['at_m'][0],eyes[2]-pile['at_m'][1])>REACH_M:
        raise ValueError('Stand within 2 m of the input hopper')
    survey=app.live.act({'session':app.live.session.id,'op':'survey','at':pile['at_m']}).get('survey') or {}
    if 'ground_m' not in survey or not 0<=eyes[1]-float(survey['ground_m'])<=3:
        raise ValueError('Stand beside the input hopper on the ground')
    saved,refused=app.live.snapshot()
    if saved is None:raise ValueError('The world must be saveable before delivery: '+str(refused))
    if len(claims)>=MAX_CLAIMS:raise ValueError('Delivery receipt limit reached')
    if old is None:
        with workshop_library._connect(app) as db:
            _delivery_schema(db);db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM world_goods_deliveries WHERE scene=?',(room.scene,)).fetchone()[0]>=MAX_CLAIMS:
                raise ValueError('Delivery reservation limit reached')
            table,column,available=_personal_meter(db,owner,substance)
            if mass>available:raise ValueError('Not enough '+substance+' in your personal Inventory')
            db.execute(f'UPDATE {table} SET mass_kg=mass_kg-? WHERE owner_id=? AND {column}=?',(packet[substance],owner,substance))
            db.execute("INSERT INTO world_goods_deliveries VALUES (?,?,?,?,?,'reserved')",
                       (room.scene,request,owner,pile['name'],encoded))
    # The live destination and receipt stay paired even if persistence fails.
    receiving_before=deepcopy(pile['holds'])
    try:
        app.brains.goods.put(*pile['at_m'],packet,named=pile['name'])
        claims.append({'request_id':request,'owner':owner,'pile':pile['name'],'goods':packet})
    except Exception:
        pile['holds']=receiving_before
        raise
    app.brains.goods.activity('dump',packet,{'player':owner,'point_m':[eyes[0],eyes[1]-.3,eyes[2]]},
                             {'pile':pile['name']},'player')
    if not keep(app,'deliver personal material to machine input'):
        raise ValueError('Delivery awaits a world save; retry the same request')
    _settle_deliveries(app)
    return {'delivered':packet,'pile':pile['name'],'repeated':False,'goods':app.brains.goods.holders()}


def _deliver_raw(app,owner,body,packet):
    """Raw source debit and hopper receipt share the same atomic room save."""
    from mcp import fabrication as model
    import fabrication_room, workshop_install
    if not {'lot_id','pile','substance','mass_kg','revision','request_id'}<=set(body):
        raise ValueError('Stored input needs its lot, quantity and current revision')
    room=app.room
    state=deepcopy(fabrication_room._state(room))
    model.advance(state,app.live.session.state['t'])
    lot=model.token(body['lot_id'],'lot_id')
    source_owner=state.get('raw_lot_ownership',{}).get(lot,{}).get('owner','')
    if source_owner and source_owner!=owner:raise ValueError('This raw material belongs to another player')
    action={k:body[k] for k in ('lot_id','pile','substance','mass_kg','revision','request_id')}
    action['mass_kg']=next(iter(packet.values()));action['op']='raw_input_delivery'
    old=state.get('raw_input_deliveries',{}).get(body['request_id'])
    if old is not None and old['owner']!=owner:raise ValueError('This raw delivery belongs to another player')
    if model.check_request(state,action):
        return {'delivered':packet,'pile':body['pile'],'repeated':True,'goods':app.brains.goods.holders()}
    if body.get('session')!=app.live.session.id:raise ValueError('The source world changed; refresh before loading')
    pile,accepted=_delivery_inputs(app,body['pile'])
    if body['substance'] not in accepted:raise ValueError('This machine input does not accept '+body['substance'])
    eyes=(player_world.records(app)[owner].get('pose') or {}).get('eyes_m')
    if not isinstance(eyes,list) or len(eyes)!=3 or math.hypot(eyes[0]-pile['at_m'][0],eyes[2]-pile['at_m'][1])>REACH_M:
        raise ValueError('Stand within 2 m of the input hopper')
    survey=app.live.act({'session':app.live.session.id,'op':'survey','at':pile['at_m']}).get('survey') or {}
    if 'ground_m' not in survey or not 0<=eyes[1]-float(survey['ground_m'])<=3:
        raise ValueError('Stand beside the input hopper on the ground')
    claims=room.goods_deliveries
    if len(claims)>=MAX_CLAIMS:raise ValueError('Delivery receipt limit reached')
    saved=workshop_install._snapshot(app.live)
    receiving_before=deepcopy(pile['holds'])
    state,_=model.deliver_raw_input(state,action,owner)
    claim={'request_id':body['request_id'],'owner':owner,'pile':body['pile'],'goods':packet,'raw_lot_id':lot}
    try:
        app.brains.goods.put(*pile['at_m'],packet,named=pile['name'])
        claims.append(claim)
        save_error=fabrication_room._persist(app,room,saved,state,recover_ack=True)
    except Exception:
        pile['holds']=receiving_before
        if claim in claims:claims.remove(claim)
        raise
    if save_error is not None:raise save_error
    app.brains.goods.activity('dump',packet,{'player':owner,'point_m':[eyes[0],eyes[1]-.3,eyes[2]]},
        {'pile':pile['name']},'player')
    return {'delivered':packet,'pile':pile['name'],'repeated':False,'goods':app.brains.goods.holders()}
