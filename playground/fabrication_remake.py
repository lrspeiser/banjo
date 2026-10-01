"""Bind reviewed Lab designs and optional carried sources to finite work.

Remake manufactures a separate product from new stock. It never heals, removes,
refunds or reconstructs the original. Initial planning is read-only; accepted
jobs retain the source diagnostic/topology hashes and target design durably.
"""
from copy import deepcopy
import time
import uuid

from mcp import fabrication as model
import inventory
import inventory_room
import workshop_install as install
import workshop_library as library

MAX_PLANS=32
LIFETIME_S=300


def _owner(app):return library.rack_owner_id(app)


def _cache(app):
    cache=getattr(app,'_fabrication_remake_plans',None)
    if cache is None:cache=app._fabrication_remake_plans={}
    now=time.monotonic()
    for ident in list(cache):
        if cache[ident]['expires']<=now:del cache[ident]
    return cache


def source(app, live, item_id):
    """Only the authenticated player's current hands/bag may supply a source."""
    if not isinstance(item_id,str) or not 1<=len(item_id)<=160:
        raise ValueError('Select a carried item in Inventory first')
    who=_owner(app);actor=who if getattr(app,'world_id',None) else ''
    shown=inventory_room.shown(app,actor)
    entries=list(shown['hands'].values())+shown['stowed']
    carried=next((e for e in entries if e and e['id']==item_id),None)
    if carried is None:raise ValueError('That item is no longer in your hands or bag')
    item=next((i for i in inventory.items_of(app.room.spec) if i['id']==item_id),None)
    if item is None:raise ValueError('The selected item has no current world geometry')
    names=sorted(set(item['bodies']))
    if not 1<=len(names)<=64:raise ValueError('Selected item exceeds the source body budget')
    snapshot=install._snapshot(live)
    native={b['name']:b for b in snapshot['bodies']}
    readings=live.session.send(op='condition',names=names)['condition']['bodies']
    covered={n for r in readings for n in r.get('source_parts',[])}
    missing=[n for n in names if n not in native and n not in covered]
    if missing:raise ValueError('Selected source geometry is incomplete: '+', '.join(missing))
    if any(r.get('state') in ('unresolved','broken') for r in readings):
        raise ValueError('Resolve the selected item fracture before planning a remake')
    # Joined native parts may report an authored member as missing while their
    # source_parts explicitly cover it. No inferred name-prefix membership.
    readings=[r for r in readings if r['name'] in native or r['name'] not in covered]
    actual={n:native[n] for n in names if n in native}
    topology={n:{k:v for k,v in b.items() if k not in ('pose','awake','color_rgba')}
              for n,b in actual.items()}
    kerfs={n:(snapshot.get('kerfs') or {}).get(n,[]) for n in actual}
    signature={'scene':app.room.scene,'owner':who,'source_item':item_id,
        'source_bodies':names,'item':item,'condition':readings,'topology':topology,'kerfs':kerfs}
    return {'schema':'banjo.remake-source.v1','owner':who,'source_item':item_id,
        'source_bodies':names,'source_hash':model.digest(signature),
        'native_hash':model.digest({'bodies':actual,'kerfs':kerfs}),
        'condition':deepcopy(readings)}


def require_owner(app,job):
    binding=job.get('remake_source') or job.get('make_source')
    if binding is not None and binding['owner']!=_owner(app):
        raise ValueError('Only the player who started this '+('remake' if job.get('remake_source') else 'make')+' may control or place it')


def plan(app,body,*,making=False):
    import fabrication_room as api
    with install._world(app) as (room,live,old),api.LOCK:
        install._source(room,old,body)
        binding=({'schema':'banjo.make-source.v1','owner':_owner(app)} if making
                 else source(app,live,body['source_item']))
        binding['draft_hash']=model.digest(body['candidate'])
        kind='make' if making else 'remake'
        state=deepcopy(getattr(room,'fabrication_record',None))
        if state is None:
            return {'schema':'banjo.'+kind+'-plan.v1','session':old.id,'scene':room.scene,
                'available':False,'reason':'No workbench process is declared in this world',
                'source':binding,'changes_world':False}
        model.validate_state(state);model.advance(state,old.state['t'])
        import fabrication_stock
        fabrication_stock.validate(app,room.scene,state)
        # Derive the minimum feed from native occupied geometry. Do not use the
        # recipe BOM or charge for whatever rounded number the page displays.
        preliminary=api.compile_quote(body['candidate'],10000.,old.spec['cell_m'],state)
        quote=api.compile_quote(body['candidate'],preliminary['product_kg'],old.spec['cell_m'],state)
        (model.make_source if making else model.remake_source)(binding)
        ident=uuid.uuid4().hex;cache=_cache(app)
        if len(cache)>=MAX_PLANS:raise ValueError('Too many fabrication plans; wait for old plans to expire')
        cache[ident]={'expires':time.monotonic()+LIFETIME_S,'scene':room.scene,'kind':kind,
            'source':binding,'quote':quote,'config_hash':model.digest(state['config'])}
        material=quote['material']
        sources=fabrication_stock.sources(app)
        available=state['stock_kg'].get(material,0.)
        return {'schema':'banjo.'+kind+'-plan.v1','plan_id':ident,'session':old.id,'scene':room.scene,
            'available':True,'source':deepcopy(binding),'quote':quote,'revision':state['revision'],
            'station_stock_kg':available,'station_energy_j':state['energy_j'],
            'missing_stock_kg':max(0.,quote['stock_kg']-available),
            'missing_energy_j':max(0.,quote['supply_required_j']-state['energy_j']),
            'stock_sources':[r for r in sources if r['material']==material],
            'occupied':any(j['status']=='running' for j in state['jobs'].values()),
            'changes_world':False,'original_retained':not making}


def start(app,body,*,making=False):
    import fabrication_room as api
    import fabrication_stock
    model.token(body['plan_id'],'plan_id')
    with install._world(app) as (room,live,old),api.LOCK:
        if body['scene']!=room.scene:raise ValueError('The source room changed')
        state=deepcopy(api._state(room));model.advance(state,old.state['t'])
        fabrication_stock.validate(app,room.scene,state)
        kind='make' if making else 'remake'
        action={'op':'start',kind+'_plan_id':body['plan_id'],'revision':body['revision'],
            'request_id':body['request_id'],'requested_by':_owner(app)}
        if model.check_request(state,action):
            require_owner(app,state['jobs'][body['request_id']])
            return {'session':old.id,'scene':room.scene,'state':model.report(state),
                'job_id':body['request_id'],'replayed':True,'original_retained':not making}
        install._source(room,old,body)
        entry=_cache(app).get(body['plan_id'])
        if entry is None:raise ValueError(kind.title()+' plan expired; review the current design again')
        if entry['scene']!=room.scene or entry['source']['owner']!=_owner(app):
            raise ValueError('This '+kind+' plan belongs to another world or player')
        if entry.get('kind','remake')!=kind:raise ValueError('Review the requested make or remake operation again')
        current=None
        if not making:
            current=source(app,live,entry['source']['source_item'])
            if current['source_hash']!=entry['source']['source_hash']:
                raise ValueError('Selected item changed; review a new remake plan')
        if model.digest(state['config'])!=entry['config_hash']:
            raise ValueError('Workbench process changed; review a new '+kind+' plan')
        quote=deepcopy(entry['quote'])
        if state['energy_j']+1e-10<quote['supply_required_j']:
            raise ValueError('Charge the workbench before starting this '+kind)
        binding=deepcopy(entry['source'])
        if current is not None:binding['native_hash']=current['native_hash']
        quote[kind+'_source']=binding
        state,replayed=model.mutate(state,action,quote=quote)
        api._persist(app,room,install._snapshot(live),state)
        return {'session':old.id,'scene':room.scene,'state':model.report(state),
            'job_id':body['request_id'],'replayed':replayed,'original_retained':not making}
