"""Constituent receipt allocation for the declared cold-stock forming process.

This preserves source volume and identity across an explicitly paid formation.
It does not simulate machining, stone fracture, grain or transported heat.
Native collection and its ground withdrawal must be saved with receive_matter.
"""
from copy import deepcopy
import math

from mcp import engine_materials


def _kind(cell):
    # Native RunKind is serialized as its stable integer. Keep it untouched
    # in provenance; group it only for the existing bulk volume ledger.
    value=cell.get('run_kind')
    if type(value) is int:
        return 'soil' if value in (1,3) else 'sand' if value==2 else 'rock' if value in (0,4,5,6,7) else None
    return value


def _craftable(cell):
    # Ore and clay share a legacy bulk rock account, not a stone forming law.
    return cell.get('run_kind') in ('rock',0,4)


def stone_pick_recipe():
    """Ordinary generic tool; terrain rock uses its existing concrete law."""
    from mcp import workshop
    design=workshop.assemble('field-pick',design_id='gathered-stone-pick',parameters={
        'length_m':.8,'arm_m':.32,'section_m':.08,'material':'oak'})
    return {'kind':design.kind,'design_id':design.design_id,'parameters':dict(design.parameters),
            'component_overrides':{'arm':{'material':'concrete'}}}


def available_materials(state,owner):
    """Owned, unspent constituent input only; legacy bulk rock is not enough."""
    from mcp import fabrication as f
    raw=f.raw_inventory(state); kg=0.;used=_used(state)
    for ident,lot in state.get('matter_lots',{}).items():
        if lot['owner']!=owner:continue
        if any(r['lot_id']==ident for field in ('raw_returns','raw_input_deliveries') for r in state.get(field,{}).values()):continue
        remaining=sum(max(0.,c['volume_m3']-used.get((ident,c['id']),0.))*2400.
                      for c in lot['packet']['cells'] if _craftable(c))
        kg+=min(remaining,sum(r['mass_kg'] for r in raw.get(ident,[]) if r['substance']=='rock'))
    return {'concrete':kg} if kg>1e-10 else {}


def source_note(state,owner,materials):
    """Explain visible legacy bulk without inventing its lost constituent cells."""
    if not materials.get('concrete',0):return None
    from mcp import fabrication as f
    legacy=math.fsum(item['mass_kg'] for ident,items in f.raw_inventory(state).items()
        if ident not in state.get('matter_lots',{})
        and state.get('raw_lot_ownership',{}).get(ident,{}).get('owner','') in ('',owner)
        for item in items if item['substance']=='rock')
    if legacy<=1e-10:return None
    return (f'Legacy Rock · {legacy:g} kg remains stored, but has no constituent cell record for this forming route. '
            'Loosen exposed rock, then click its loose physical material to collect native cells.')


def packet(value):
    from mcp import fabrication as f
    if not isinstance(value, dict) or value.get('schema') != 'banjo.ground-matter-transfer.v1':
        raise ValueError('Native constituent collection receipt required')
    cells=value.get('cells')
    if not isinstance(cells,list) or not 1<=len(cells)<=16000:
        raise ValueError('Constituent collection exceeds the cell budget')
    ids=set(); volumes={s+'_m3':0. for s in f.GROUND_DENSITIES}; mass=0.
    for cell in cells:
        if not isinstance(cell,dict) or not isinstance(cell.get('id'),str) or not 1<=len(cell['id'])<=200 or cell['id'] in ids:
            raise ValueError('Constituent source IDs must be unique')
        ids.add(cell['id']); kind=_kind(cell)
        if kind not in f.GROUND_DENSITIES:raise ValueError('Unsupported constituent ground material')
        size=cell.get('size_m'); center=cell.get('source_center_m')
        if not isinstance(size,list) or len(size)!=3 or not isinstance(center,list) or len(center)!=3:
            raise ValueError('Constituent cells require exact size and source center')
        for x in size:f.number(x,'cell size',1e-12,100)
        for x in center:f.number(x,'source center',-1e6,1e6)
        volume=f.number(cell.get('volume_m3'),'cell volume',1e-15,1e6)
        kg=f.number(cell.get('mass_kg'),'cell mass',1e-15,1e9)
        density=f.number(cell.get('density_kg_m3'),'cell density',1,1e6)
        if not math.isclose(volume,math.prod(size),rel_tol=1e-9,abs_tol=1e-13) or not math.isclose(kg,volume*density,rel_tol=1e-9,abs_tol=1e-10):
            raise ValueError('Constituent geometry, volume and mass do not close')
        if not math.isclose(density,f.GROUND_DENSITIES[kind],rel_tol=1e-12):
            raise ValueError('Constituent ground density changed')
        if kind=='rock' and cell.get('catalog_material',cell.get('material'))!='concrete':
            raise ValueError('Rock currently requires the declared concrete surrogate')
        volumes[kind+'_m3']+=volume; mass+=kg
    stated=value.get('volumes')
    if not isinstance(stated,dict) or any(not math.isclose(stated.get(k,0.),v,rel_tol=1e-9,abs_tol=1e-12) for k,v in volumes.items()):
        raise ValueError('Constituent receipt volumes do not close')
    if not math.isclose(f.number(value.get('mass_kg'),'receipt mass'),mass,rel_tol=1e-9,abs_tol=1e-9):
        raise ValueError('Constituent receipt mass does not close')
    f.number(value.get('source_work_j'),'collection source work')
    return value


def receive_matter(state,action,value,owner):
    """Trusted adapter only: accept native cells and their paired bulk debit."""
    from mcp import fabrication as f
    if not isinstance(owner,str) or not 1<=len(owner)<=128:raise ValueError('Matter requires its authenticated owner')
    packet(value); ident=f.token(action['request_id'])
    if f.check_request(state,action):
        if state.get('matter_lots',{}).get(ident)!={'owner':owner,'packet':value}:
            raise ValueError('Matter request belongs to another collection or player')
        return deepcopy(state),True
    existing={c['id'] for lot in state.get('matter_lots',{}).values() for c in lot['packet']['cells']}
    if any(c['id'] in existing for c in value['cells']):raise ValueError('Constituent cell was already collected')
    contents=[{'substance':s,'volume_m3':value['volumes'].get(s+'_m3',0.),
               'mass_kg':value['volumes'].get(s+'_m3',0.)*rho}
              for s,rho in f.GROUND_DENSITIES.items() if value['volumes'].get(s+'_m3',0.)>0]
    bulk={'schema':'banjo.bulk-material.v1','source':'excavated_ground','form':f._bulk_form(contents),
          'thermal_state':'unmodeled','contents':contents}
    out,_=f.receive_bulk(state,action,bulk)
    out.setdefault('matter_lots',{})[ident]={'owner':owner,'packet':deepcopy(value)}
    out.setdefault('raw_lot_ownership',{})[ident]={'owner':owner,'source_actor':owner}
    f.validate_state(out)
    return out,False


def _used(state):
    used={}
    for entry in state.get('raw_make_inputs',{}).values():
        for part in entry['allocations']:
            key=(part['lot_id'],part['source_id']); used[key]=used.get(key,0.)+part['volume_m3']
    return used


def plan(state,owner,quote):
    """Use owned native rock first; quote alone never reserves anything."""
    from mcp import fabrication as f
    out=deepcopy(quote); needed=max(0.,f.materials(quote,'stock').get('concrete',0.)-state['stock_kg'].get('concrete',0.))
    if needed<=1e-10:return out
    used=_used(state); allocations=[]; available=f.raw_inventory(state)
    for ident,lot in sorted(state.get('matter_lots',{}).items()):
        if lot['owner']!=owner:continue
        # Aggregate returns do not retain a per-cell selection. They cannot
        # authorize reuse of that lot's original constituent state.
        if any(r['lot_id']==ident for field in ('raw_returns','raw_input_deliveries') for r in state.get(field,{}).values()):continue
        left=next((r['volume_m3'] for r in available.get(ident,[]) if r['substance']=='rock'),0.)
        for cell in lot['packet']['cells']:
            if not _craftable(cell):continue
            volume=min(left,max(0.,cell['volume_m3']-used.get((ident,cell['id']),0.)),needed/2400.)
            if volume<=1e-14:continue
            allocations.append({'lot_id':ident,'source_id':cell['id'],'volume_m3':volume,
                'mass_kg':volume*2400.,'source_fraction':volume/cell['volume_m3'],'source_cell':deepcopy(cell)})
            needed=max(0.,needed-volume*2400.);left=max(0.,left-volume)
            if needed<=1e-10:break
        if needed<=1e-10:break
    if allocations:
        out['raw_matter']={'schema':'banjo.fabrication-matter-allocation.v1','owner':owner,'allocations':allocations,
            'materials_kg':{'concrete':math.fsum(a['mass_kg'] for a in allocations)},
            'law':'declared-cold-stock-shaping-v1','source_material':'terrain rock (concrete surrogate)',
            'state_boundary':'Source cell state retained as provenance; formed geometry is paid cold-stock resampling, not fracture or state-preserving machining.',
            'product_materials_kg':deepcopy(f.materials(quote,'product')),
            'offcuts_materials_kg':{m:kg-f.materials(quote,'product').get(m,0.) for m,kg in f.materials(quote,'stock').items()}}
        source=out['raw_matter']
        source['formation_work_j']=quote['required_j']
        if quote.get('formation_cells'):
            # Keep the accepted output cell set as well as the original cut
            # cells. Forming may resample a 5 cm source into a 4 cm product;
            # the volume mapping records every piece rather than rounding.
            stock_kg=f.materials(quote,'stock')['concrete']
            product_kg=f.materials(quote,'product')['concrete']
            made_ratio=product_kg/stock_kg
            fraction=source['materials_kg']['concrete']/stock_kg
            pool=[{**a,'left':a['volume_m3']*made_ratio} for a in allocations]
            target=[];cursor=0
            for cell in quote['formation_cells']:
                if engine_materials.canonical(cell['material'])!='concrete':continue
                volume=quote['cell_m']**3;wanted=volume*fraction;pieces=[]
                while wanted>1e-14 and cursor<len(pool):
                    part=pool[cursor];take=min(wanted,part['left'])
                    if take>1e-14:pieces.append({'lot_id':part['lot_id'],'source_id':part['source_id'],'volume_m3':take,'mass_kg':take*2400.})
                    part['left']-=take;wanted-=take
                    if part['left']<=1e-14:cursor+=1
                if wanted>1e-12:raise ValueError('Constituent-to-formed-cell volume does not close')
                target.append({'cell':deepcopy(cell),'volume_m3':volume,'mass_kg':volume*2400.,'raw_sources':pieces})
            source['formed_cells']=target
            source['raw_offcuts']=[{'lot_id':a['lot_id'],'source_id':a['source_id'],
                'volume_m3':a['volume_m3']*(1-made_ratio),'mass_kg':a['mass_kg']*(1-made_ratio)} for a in allocations]
    return out


def reserve(state,quote,job_id,owner):
    """Part of start's atomic candidate, not a separate credit operation."""
    from mcp import fabrication as f
    matter=quote.get('raw_matter')
    if matter is None:return
    if matter['owner']!=owner:raise ValueError('Raw crafting inputs belong to another player')
    refreshed=plan(state,owner,{k:v for k,v in quote.items() if k!='raw_matter'}).get('raw_matter')
    if refreshed!=matter:raise ValueError('Raw crafting inputs changed; review the design again')
    state.setdefault('raw_make_inputs',{})[job_id]=deepcopy(matter)
    for material,kg in matter['materials_kg'].items():state['stock_kg'][material]=state['stock_kg'].get(material,0.)+kg


def validate(state):
    from mcp import fabrication as f
    lots=state.get('matter_lots',{})
    if not isinstance(lots,dict) or len(lots)>4096:raise ValueError('Invalid constituent matter lots')
    seen=set()
    for ident,lot in lots.items():
        f.token(ident,'matter lot'); f.obj(lot,{'owner','packet'},{'owner','packet'});packet(lot['packet'])
        if state.get('raw_lot_ownership',{}).get(ident,{}).get('owner')!=lot['owner']:raise ValueError('Constituent lot owner changed')
        contents={r['substance']:r for r in state.get('raw_lots',{}).get(ident,{}).get('contents',[])}
        for kind in f.GROUND_DENSITIES:
            if not math.isclose(contents.get(kind,{}).get('volume_m3',0.),lot['packet']['volumes'].get(kind+'_m3',0.),rel_tol=1e-9,abs_tol=1e-12):
                raise ValueError('Constituent lot lost its paired bulk receipt')
        for cell in lot['packet']['cells']:
            if cell['id'] in seen:raise ValueError('Constituent cell duplicated across lots')
            seen.add(cell['id'])
    imports=state.get('raw_make_inputs',{})
    if not isinstance(imports,dict) or len(imports)>f.MAX_JOBS:raise ValueError('Invalid raw make inputs')
    for ident,entry in imports.items():
        job=state.get('jobs',{}).get(ident,{})
        if job.get('raw_matter')!=entry:raise ValueError('Raw input requires its exact paid workpiece')
        if entry.get('law')!='declared-cold-stock-shaping-v1' or entry.get('formation_work_j')!=job['required_j']:
            raise ValueError('Raw forming law or paid work changed')
        if entry['product_materials_kg']!=f.materials(job,'product') or entry['offcuts_materials_kg']!={
            m:kg-f.materials(job,'product').get(m,0.) for m,kg in f.materials(job,'stock').items()}:
            raise ValueError('Raw formed product or offcut allocation changed')
        mass=0.
        for part in entry['allocations']:
            lot=lots.get(part['lot_id'])
            source=next((c for c in lot['packet']['cells'] if c['id']==part['source_id']),None) if lot else None
            if source!=part['source_cell'] or lot['owner']!=entry['owner'] or not _craftable(source):
                raise ValueError('Raw make source state or ownership changed')
            volume=f.number(part['volume_m3'],'allocated volume',1e-15,source['volume_m3'])
            if not math.isclose(part['mass_kg'],volume*2400.,rel_tol=1e-12,abs_tol=1e-10) or not math.isclose(part['source_fraction'],volume/source['volume_m3'],rel_tol=1e-12):
                raise ValueError('Raw make source allocation does not close')
            mass+=part['mass_kg']
        if set(entry['materials_kg'])!={'concrete'} or not math.isclose(mass,entry['materials_kg']['concrete'],rel_tol=1e-12,abs_tol=1e-9):
            raise ValueError('Raw make material mass does not close')
        if mass>f.materials(job,'stock').get('concrete',0.)+1e-9:raise ValueError('Raw input exceeds the paid stock')
        if job.get('formation_cells'):
            expected=[c for c in job['formation_cells'] if engine_materials.canonical(c['material'])=='concrete']
            if [c['cell'] for c in entry.get('formed_cells',[])]!=expected:
                raise ValueError('Formed cells changed the accepted native shape')
            mapped={};allocated={(p['lot_id'],p['source_id']):p['volume_m3'] for p in entry['allocations']}
            fraction=mass/f.materials(job,'stock')['concrete']
            for cell in entry['formed_cells']:
                if not math.isclose(cell['volume_m3'],job['cell_m']**3,rel_tol=1e-12) or not math.isclose(cell['mass_kg'],cell['volume_m3']*2400.,rel_tol=1e-12):
                    raise ValueError('Formed cell mass or volume changed')
                if not math.isclose(sum(p['volume_m3'] for p in cell['raw_sources']),cell['volume_m3']*fraction,rel_tol=1e-9,abs_tol=1e-12):
                    raise ValueError('Formed cell source volume does not close')
            for part in [p for c in entry['formed_cells'] for p in c['raw_sources']]+entry.get('raw_offcuts',[]):
                key=(part['lot_id'],part['source_id'])
                if key not in allocated or not math.isclose(part['mass_kg'],part['volume_m3']*2400.,rel_tol=1e-12,abs_tol=1e-10):
                    raise ValueError('Formed matter has an unrelated source')
                f.number(part['volume_m3'],'formed source volume',0,allocated[key])
                mapped[key]=mapped.get(key,0.)+part['volume_m3']
            if any(not math.isclose(mapped.get(k,0.),v,rel_tol=1e-9,abs_tol=1e-12) for k,v in allocated.items()):
                raise ValueError('Source cell, product and offcut volumes do not close')
    for (ident,source_id),volume in _used(state).items():
        source=next(c for c in lots[ident]['packet']['cells'] if c['id']==source_id)
        if volume>source['volume_m3']+1e-12:raise ValueError('Constituent source cell spent twice')


def subtract_raw(state,remaining):
    for entry in state.get('raw_make_inputs',{}).values():
        for part in entry['allocations']:
            have=remaining[part['lot_id']]['rock']
            have['volume_m3']-=part['volume_m3'];have['mass_kg']-=part['mass_kg']
            if have['volume_m3'] < -1e-12 or have['mass_kg'] < -1e-9:raise ValueError('Raw make exceeds its source lot')
            have['volume_m3']=max(0.,have['volume_m3']);have['mass_kg']=max(0.,have['mass_kg'])
