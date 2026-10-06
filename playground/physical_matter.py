"""Paid reduced cutting and durable collection of native constituent matter.

Banked energy is a finite external work reservoir, not simulated wiring. The
native cut law owns resistance, partial work, cells and rigid-body motion.
An uncertain debit remains reserved until the same native request is saved.
"""
from copy import deepcopy
import json
import math
import re
from types import SimpleNamespace

import market
import workshop_library
import world_access

REQUEST = re.compile(r'[A-Za-z0-9_-]{8,80}\Z')
MAX_WORK_J = 500_000


def _schema(db):
    market._schema(db)
    db.execute('''CREATE TABLE IF NOT EXISTS ground_work_orders (
        request_id TEXT PRIMARY KEY, owner TEXT NOT NULL, action TEXT NOT NULL,
        reserved_j INTEGER NOT NULL CHECK(reserved_j>=0),
        consumed_j INTEGER, status TEXT NOT NULL CHECK(status IN ('reserved','applied')),
        receipt TEXT)''')
    db.commit()


def balance(app, owner):
    with workshop_library._connect(app) as db:
        _schema(db)
        return market._balance(db, owner)


def _finish(app,request_id,owner,budget,receipt,persist):
    used=receipt.get('consumed_work_j')
    if type(used) not in (int,float) or not math.isfinite(used) or used<0 or used>budget+1e-7:
        raise ValueError('Native cut exceeded its reserved work; the debit is retained for recovery')
    if not persist(app,'native material cut'):
        raise ValueError('Cut save pending. Retry the same request; energy remains reserved.')
    charged=min(budget,math.ceil(used))
    receipt={**receipt,'request_id':request_id,'charged_j':charged,
             'wallet_rounding_j':charged-used,'energy_source':'Banked energy'}
    with workshop_library._connect(app) as db:
        _schema(db);db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT status FROM ground_work_orders WHERE request_id=?',(request_id,)).fetchone()
        if row['status']=='reserved':
            db.execute('UPDATE market_wallet SET balance_j=balance_j+? WHERE owner_id=?',(budget-charged,owner))
            db.execute("UPDATE ground_work_orders SET consumed_j=?,status='applied',receipt=? WHERE request_id=?",
                       (charged,json.dumps(receipt,allow_nan=False),request_id))
        db.commit()
    return receipt


def recover_cut(app,request_id,owner,persist):
    """Resolve already executed work without a second tool or reach action."""
    if not owner or not REQUEST.fullmatch(request_id or ''):return None
    with world_access.state_lock(app):
        with workshop_library._connect(app) as db:
            _schema(db)
            row=db.execute('SELECT * FROM ground_work_orders WHERE request_id=?',(request_id,)).fetchone()
            if row is None:return None
            if row['owner']!=owner or json.loads(row['action'])['world']!=app.world_id:
                raise ValueError('Cut request belongs to another player or world')
            if row['status']=='applied':return json.loads(row['receipt'])
            budget=row['reserved_j']
        saved,_=app.live.snapshot()
        if saved is None:return None
        source='bank:'+owner+':'+request_id
        record=((saved.get('ground') or {}).get('debris') or {}).get('receipts',{}).get(source)
        if record is None:return None
        return _finish(app,request_id,owner,budget,record['answer'],persist)


def cut(app, at, request_id, owner, persist):
    """Called only after authoritative held-tool/reach/point checks."""
    if not owner or not REQUEST.fullmatch(request_id or ''):
        raise ValueError('Join as a player and provide a stable cutting request')
    if not isinstance(at, list) or len(at) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in at):
        raise ValueError('A cut needs a finite native target')
    action=json.dumps({'world':app.world_id,'at':at},sort_keys=True,separators=(',',':'))
    with world_access.state_lock(app):
        with workshop_library._connect(app) as db:
            _schema(db); db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM ground_work_orders WHERE request_id=?',(request_id,)).fetchone()
            if previous:
                if previous['owner'] != owner or previous['action'] != action:
                    raise ValueError('Cut request belongs to another player or target')
                if previous['status']=='applied':
                    return json.loads(previous['receipt'])
                budget=previous['reserved_j']
            else:
                budget=min(MAX_WORK_J,market._balance(db,owner))
                if budget<=0:
                    return {'supported':False,'kind':'no energy','consumed_work_j':0,
                            'reason':'No banked energy. Collect solar energy in Inventory, or turn Energy assist off.'}
                db.execute('UPDATE market_wallet SET balance_j=balance_j-? WHERE owner_id=?',(budget,owner))
                db.execute('INSERT INTO ground_work_orders VALUES (?,?,?,?,NULL,\'reserved\',NULL)',
                           (request_id,owner,action,budget))
            db.commit()
        reply=app.live.session.send(op='strike-cell',at_m=at,work_j=budget,
                                    work_source='bank:'+owner+':'+request_id)
        receipt=reply.get('ground_cut') or reply.get('work_cut')
        if not isinstance(receipt,dict):
            raise ValueError('Native cut has no work receipt; the debit is reserved. Retry this request.')
        return _finish(app,request_id,owner,budget,receipt,persist)


def collect(app, body, owner):
    """Clone, withdraw and save native body plus its private lot together."""
    import fabrication_room as room_model
    import workshop_install as install
    from mcp import fabrication, matter_fabrication
    ident=body.get('request_id')
    if not owner or not REQUEST.fullmatch(ident or ''):
        raise ValueError('Collection requires a player and a stable request')
    debris_id=body.get('id')
    if type(debris_id) is not int or debris_id<=0:
        raise ValueError('Select a native material component')
    with install._world(app) as (room,live,old),room_model.LOCK:
        state=deepcopy(room_model._state(room))
        existing=state.get('matter_lots',{}).get(ident)
        if existing:
            if existing['owner']!=owner or existing['packet'].get('id')!=debris_id:
                raise ValueError('Collection request belongs to another item or player')
            return {'ok':True,'session':old.id,'replayed':True,'packet':existing['packet']}
        if body.get('session')!=old.id:
            raise ValueError('The world changed; refresh before collecting')
        # Use the authenticated stored pose, never a client-supplied location.
        profile=room.player_records.get(owner,{})
        pose=profile.get('pose') or profile.get('person') or {}
        at=pose.get('eyes_m')
        if not isinstance(at,list) or len(at)!=3:
            raise ValueError('Report your position before collecting')
        before=install._snapshot(live)
        fabrication.advance(state,before['t_s'])
        staged=install.live_session.Live()
        try:
            opened=staged.open(SimpleNamespace(engine_path=app.engine_path,runs_path=app.runs_path),
                               {'spec':deepcopy(room.spec),'snapshot':before})
            if opened.get('restored',{}).get('tier')!='whole':
                raise ValueError('Native matter could not reopen whole')
            staged.session._actor_local.actor=owner
            reply=staged.session.send(op='collect-ground-debris',id=debris_id,at_m=at,maximum_distance_m=3.)
            packet=reply.get('ground_matter_packet') or reply.get('ground_matter') or reply.get('matter_packet')
            matter_fabrication.packet(packet)
            quantities=packet['volumes']
            withdrawal=staged.session.send(op='ground_withdraw',**quantities)
            expected={v['substance']:v['volume_m3'] for v in withdrawal['material_packet']['contents']}
            if any(not math.isclose(expected.get(s,0),quantities.get(s+'_m3',0),rel_tol=1e-9,abs_tol=1e-12)
                   for s in fabrication.GROUND_DENSITIES):
                raise ValueError('Native material withdrawal does not match the collected cells')
            action={'op':'collect_matter','request_id':ident,'revision':state['revision'],'debris_id':debris_id}
            state,_=matter_fabrication.receive_matter(state,action,packet,owner)
            saved=install._snapshot(staged)
            fabrication.validate_ground_stock(state,saved,getattr(room,'ground_transfers',None))
            error=room_model._persist(app,room,saved,state,recover_ack=True)
            live.session=staged.session;staged.session=None
            live.session._actor_local.actor=owner
            live.session.on_reply=getattr(app,'on_live_reply',None)
            install._preview_cache(app).clear()
            old.close()
            if error is not None:raise error
            return {'ok':True,'session':live.session.id,'replayed':False,'packet':packet}
        finally:
            staged.shutdown()
