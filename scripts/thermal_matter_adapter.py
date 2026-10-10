"""Thermal fields on exact coupled-registry matter; mechanical owners may change.

No mechanical mass changes or thermal weakening. Heat crosses each authored
face through the part of it that is still bonded (bond()); a separated face
carries none, since contact conductance is not modelled.
"""
import copy,ctypes,hashlib,json,math,time
from pathlib import Path
from thermal_fields import MATERIALS,library_path,number
from object_registry import digest,canonical
ROOT=Path(__file__).resolve().parents[1]
SCHEMA='banjo.persistent-thermal-matter.v1'
def source_hash():
 h=hashlib.sha256()
 for name in ('scripts/thermal_matter_adapter.py','scripts/thermal_fields.py','scripts/object_registry.py','src/thermal/ThermalMatterTransfer.cpp','src/thermal/ThermalMatterTransfer.hpp','src/thermal/ThermalFieldApi.cpp','src/thermal/ThermalFieldApi.hpp','src/thermal/ThermalKernel.cpp','src/thermal/ThermalKernel.hpp','src/thermal/EnthalpyLaw.cpp','src/thermal/EnthalpyLaw.hpp'):
  h.update(name.encode());h.update((ROOT/name).read_bytes())
 return h.hexdigest()
def token(text):return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8],'big')
def rows(document):
 if not isinstance(document,dict) or document.get('schema')!='banjo.object-registry.v1':raise ValueError('Canonical registry document required')
 definitions=document['definitions'];result=[]
 for key,value in definitions.items():
  if digest(value)!=key:raise ValueError('Registry definition checksum mismatch')
 for instance in document['continuation']['instances']:
  definition=definitions[instance['definition_sha256']]
  if not(len(instance['body_ids'])==len(instance['matter_ids'])==len(definition['cells'])):raise ValueError('Registry matter mapping incomplete')
  for body,matter,cell in zip(instance['body_ids'],instance['matter_ids'],definition['cells']):
   if cell['shape']=='plane':continue
   if type(body) is not int or body<0 or not isinstance(matter,str) or not matter.startswith(document['world_id']+'/'):raise ValueError('Invalid canonical matter mapping')
   if not isinstance(instance['instance_id'],str) or not isinstance(instance['solver_binding'],str):raise ValueError('Invalid owner mapping')
   result.append(dict(body_id=body,matter_id=matter,object_id=instance['instance_id'],owner=instance['instance_id']+'/'+instance['solver_binding'],mechanical_owner=instance['solver_binding'],cell=copy.deepcopy(cell),definition_sha256=instance['definition_sha256']))
 if not 1<=len(result)<=64 or len({r['matter_id'] for r in result})!=len(result) or len({r['body_id'] for r in result})!=len(result):raise ValueError('Duplicate or missing finite matter')
 return result
class ThermalMatterAdapter:
 def __init__(self,registry,config,library=None):
  if not isinstance(config,dict) or set(config)-{'initial_temperature_k','heater_w','heater_body_id','reaction'}:raise ValueError('Unknown persistent thermal configuration')
  self.config=dict(initial_temperature_k=260.,heater_w=2.,heater_body_id=3,reaction=False);self.config.update(config)
  number(self.config['initial_temperature_k'],150,1200);number(self.config['heater_w'],0,100)
  if self.config['reaction'] is not False:raise ValueError('Moving matter does not admit reactions: oxidative mass/transport coupling unavailable')
  if type(self.config['heater_body_id']) is not int:raise ValueError('Heater requires finite canonical body ID')
  self.registry=copy.deepcopy(registry);self.mapping=rows(registry);self._signature=self.signature(registry)
  self.library=Path(library).resolve() if library else library_path();self.lib=ctypes.CDLL(str(self.library));p=ctypes.POINTER(ctypes.c_double);u=ctypes.POINTER(ctypes.c_uint64)
  self.lib.banjo_thermal_field_step.argtypes=[p,ctypes.c_int,p,ctypes.c_int,ctypes.c_double,p,p];self.lib.banjo_thermal_field_step.restype=ctypes.c_int
  self.lib.banjo_thermal_field_observe.argtypes=[p,ctypes.c_int,p];self.lib.banjo_thermal_field_observe.restype=ctypes.c_int
  self.lib.banjo_thermal_matter_rebind.argtypes=[p,u,u,u,u,ctypes.c_int,p,p];self.lib.banjo_thermal_matter_rebind.restype=ctypes.c_int
  self.identity=dict(source_sha256=source_hash(),binary_sha256=hashlib.sha256(self.library.read_bytes()).hexdigest())
  self.cells=[];self.links=[];self.time=number(registry['continuation']['time_s'],0,1e9);self.external=0.;self.elapsed=0.;self.receipts=[];self.transfers=[]
  for r in self.mapping:
   c=r['cell'];props=c['material'];name=props['material']
   if name not in MATERIALS:raise ValueError('No explicit thermal property declaration for this material')
   law=MATERIALS[name];half=c['half_size_m'];volume=4*math.pi*half[0]**3/3 if c['shape']=='sphere' else 8*math.prod(half)
   mass=props['density_kg_m3']*volume
   if mass<=0 or mass>100:raise ValueError('Finite thermal mass outside admitted range')
   if not c['prescribed'] and abs(c['solver_mass_kg']-mass)>1e-12*max(1,mass):raise ValueError('Mechanical/thermal mass mismatch')
   temp=self.config['initial_temperature_k'];h=law['cs']*temp
   if law['latent'] and temp>273.15:h=law['cs']*273.15+law['latent']+law['cl']*(temp-273.15)
   self.cells.append([mass,mass*h,law['cs'],law['cl'],273.15,law['latent'],0.,0.,mass,0.,0.,0.,600.,1.5,self.config['heater_w'] if r['body_id']==self.config['heater_body_id'] else 0.,0.])
   r['thermal_law']=copy.deepcopy(law)
  if self.config['heater_body_id'] not in [r['body_id'] for r in self.mapping]:raise ValueError('Heater targets infinite or missing matter')
  # Use each unique authored full face once; native cohesive quadrature sites
  # share that face, so they must not multiply thermal conductance.
  by_matter={r['matter_id']:i for i,r in enumerate(self.mapping)}
  for instance in registry['continuation']['instances']:
   definition=registry['definitions'][instance['definition_sha256']];local={c['local_matter_id']:instance['matter_ids'][i] for i,c in enumerate(definition['cells'])};seen=set()
   for edge in definition['interfaces']:
    a,b=[by_matter[local[x]] for x in edge['matter_ids']];key=tuple(sorted((a,b)))
    if key in seen:continue
    seen.add(key);ca,cb=self.mapping[a]['cell'],self.mapping[b]['cell'];ha,hb=ca['half_size_m'],cb['half_size_m']
    if ca['shape']!='cube' or cb['shape']!='cube' or max(ha)-min(ha)>1e-12 or max(hb)-min(hb)>1e-12:raise ValueError('Thermal face geometry requires existing cubic material cells')
    distance=math.dist(ca['reference_position_m'],cb['reference_position_m']);area=(2*min(ha[0],hb[0]))**2
    ka,kb=self.mapping[a]['thermal_law']['conductivity'],self.mapping[b]['thermal_law']['conductivity'];g=(2*ka*kb/(ka+kb))*area/distance if ka and kb else 0.
    self.links.append([a,b,g])
  # The authored (fully bonded) conductance of each face; links carry it
  # times the face's bonded fraction.
  self.bonded_links=[list(link) for link in self.links]
  self.initial_energy=math.fsum(c[1] for c in self.cells);self.initial_mass=math.fsum(c[0] for c in self.cells);self._initial_cells=copy.deepcopy(self.cells);self._initial_time=self.time
  self.observations()
 @staticmethod
 def signature(document):return digest(dict(world_id=document['world_id'],definitions=document['definitions'],matter=sorted((r['matter_id'],r['body_id'],r['object_id'],r['definition_sha256']) for r in rows(document))))
 @staticmethod
 def array(values):return (ctypes.c_double*len(values))(*values)
 def observations(self):
  out=(ctypes.c_double*(2*len(self.cells)))();raw=self.array([v for c in self.cells for v in c])
  if self.lib.banjo_thermal_field_observe(raw,len(self.cells),out):raise ValueError('Persistent native thermal state refused')
  return [[out[2*i],out[2*i+1]] for i in range(len(self.cells))]
 def clone(self):
  result=object.__new__(type(self));result.__dict__={k:v if k in ('lib','library') else copy.deepcopy(v) for k,v in self.__dict__.items()};return result
 def bond(self,fractions):
  """Set each face's bonded fraction (1 intact, 0 separated), by body pair.

  Heat conducts through the bonded part of a face only: a crack opens a gap
  that this model does not carry heat across. Faces not named keep their
  fraction. Moving heat between cells conserves the field's energy whatever
  the conductance, so the energy account is unchanged.
  """
  by_body={r['body_id']:i for i,r in enumerate(self.mapping)};index={}
  for k,(a,b,_) in enumerate(self.bonded_links):index[tuple(sorted((a,b)))]=k
  for (body_a,body_b),fraction in fractions.items():
   fraction=number(fraction,0,1)
   if body_a not in by_body or body_b not in by_body:raise ValueError('Bonded fraction names matter outside the thermal field')
   k=index.get(tuple(sorted((by_body[body_a],by_body[body_b]))))
   if k is None:raise ValueError('Bonded fraction names a face with no authored heat path')
   self.links[k][2]=self.bonded_links[k][2]*fraction
 def advance(self,duration_s):
  duration=number(duration_s,1e-15,1.);saved=self.clone();start=time.perf_counter();remaining=duration
  try:
   while remaining>0:
    dt=min(.25,remaining);raw=self.array([v for c in self.cells for v in c]);links=self.array([v for e in self.links for v in e]);out=(ctypes.c_double*(16*len(self.cells)))();audit=(ctypes.c_double*8)()
    if self.lib.banjo_thermal_field_step(raw,len(self.cells),links,len(self.links),dt,out,audit):raise ValueError('Native persistent field interval refused; thermal state restored')
    self.cells=[list(out[i*16:(i+1)*16]) for i in range(len(self.cells))];self.external+=audit[2];self.receipts.append(dict(dt_s=dt,external_heat_j=audit[2],energy_residual_j=audit[6],mass_residual_kg=audit[5]-audit[4]));remaining=max(0.,remaining-dt)
   self.time+=duration;self.elapsed+=time.perf_counter()-start;self.receipts=self.receipts[-64:]
  except Exception:self.__dict__=saved.__dict__;raise
 def rebind(self,registry):
  if self.signature(registry)!=self._signature:raise ValueError('Field ownership transfer edits immutable matter/geometry/material')
  if abs(number(registry['continuation']['time_s'],0,1e9)-self.time)>1e-12:raise ValueError('Mechanical/thermal clocks differ at transfer')
  mapping=rows(registry);oldids=[token(r['matter_id']) for r in self.mapping];newids=[token(r['matter_id']) for r in mapping]
  if len(set(oldids))!=len(oldids) or len(set(newids))!=len(newids):raise ValueError('Persistent ID token collision')
  src=self.array([v for c in self.cells for v in c]);out=(ctypes.c_double*len(src))();audit=(ctypes.c_double*7)();n=len(mapping);u=lambda values:(ctypes.c_uint64*len(values))(*values)
  if self.lib.banjo_thermal_matter_rebind(src,u(oldids),u([token(r['owner']) for r in self.mapping]),u(newids),u([token(r['owner']) for r in mapping]),n,out,audit):raise ValueError('Native matter transfer rejected; prior fields unchanged')
  old={r['matter_id']:r for r in self.mapping};newindices={r['matter_id']:i for i,r in enumerate(mapping)}
  remap=lambda links:[[newindices[self.mapping[a]['matter_id']],newindices[self.mapping[b]['matter_id']],g] for a,b,g in links]
  for r in mapping:r['thermal_law']=old[r['matter_id']]['thermal_law']
  receipt=dict(time_s=self.time,changed_owner_count=int(audit[6]),thermal_energy_residual_j=audit[1]-audit[0],chemical_energy_residual_j=audit[3]-audit[2],species_mass_residual_kg=audit[5]-audit[4],matter_ids=[r['matter_id'] for r in mapping])
  cells=[list(out[16*i:16*(i+1)]) for i in range(n)];links=remap(self.links);bonded_links=remap(self.bonded_links)
  # Mutation only after every native/metadata allocation has succeeded.
  document=copy.deepcopy(registry);transfers=(self.transfers+[receipt])[-64:]
  self.cells,self.links,self.bonded_links,self.mapping,self.registry,self.transfers=cells,links,bonded_links,mapping,document,transfers
 def snapshot(self,bodies=None):
  observations=self.observations();values=[]
  for i,(r,c) in enumerate(zip(self.mapping,self.cells)):
   value=dict(matter_id=r['matter_id'],object_id=r['object_id'],body_id=r['body_id'],mechanical_owner=r['mechanical_owner'],thermal_mass_kg=c[0],thermal_energy_j=c[1],temperature_k=observations[i][0],liquid_fraction=observations[i][1],species_mass_kg=sum(c[6:10]),fuel_kg=c[6],oxygen_kg=c[7],products_kg=c[9])
   if bodies is not None:
    row=bodies[r['body_id']];value['position_m']=[float(x) for x in row[7:10]]
    if not all(math.isfinite(x) for x in value['position_m']):raise ValueError('Nonfinite current mechanical geometry')
   values.append(value)
  return dict(schema=SCHEMA,implementation=copy.deepcopy(self.identity),time_s=self.time,fields=values,audit=dict(external_heat_j=self.external,energy_residual_j=math.fsum(c[1] for c in self.cells)-self.initial_energy-self.external,mass_residual_kg=math.fsum(sum(c[6:10]) for c in self.cells)-self.initial_mass,calculation_wall_s=self.elapsed),last_transfer=copy.deepcopy(self.transfers[-1]) if self.transfers else None,scope='Persistent finite material fields; conduction through each authored face in proportion to its bonded fraction; no reactions, contact heat across separated faces, expansion or weakening')
 def export_checkpoint(self):
  return copy.deepcopy(dict(schema=SCHEMA,implementation=self.identity,config=self.config,registry=self.registry,cells=self.cells,time_s=self.time,external_heat_j=self.external,initial_time_s=self._initial_time,initial_energy_j=self.initial_energy,initial_mass_kg=self.initial_mass,transfers=self.transfers,receipts=self.receipts))
 @classmethod
 def restore(cls,checkpoint,registry,library=None):
  required={'schema','implementation','config','registry','cells','time_s','external_heat_j','initial_time_s','initial_energy_j','initial_mass_kg','transfers','receipts'}
  if not isinstance(checkpoint,dict) or set(checkpoint)!=required or checkpoint['schema']!=SCHEMA:raise ValueError('Invalid persistent thermal checkpoint')
  result=cls(registry,checkpoint['config'],library)
  if checkpoint['implementation']!=result.identity or checkpoint['registry']!=registry:raise ValueError('Persistent field source/binary/registry mismatch')
  cells=checkpoint['cells']
  if not isinstance(cells,list) or len(cells)!=len(result.cells):raise ValueError('Incomplete persistent fields')
  for before,cell in zip(result.cells,cells):
   if not isinstance(cell,list) or len(cell)!=16:raise ValueError('Invalid persistent field record')
   for v in cell:number(v,0,1e10)
   if any(cell[i]!=before[i] for i in range(16) if i!=1):raise ValueError('Field checkpoint changes fixed mass/species/material law')
  result.cells=copy.deepcopy(cells);result.time=number(checkpoint['time_s'],0,1e9);result.external=number(checkpoint['external_heat_j'],0,1e9);result._initial_time=number(checkpoint['initial_time_s'],0,result.time)
  if checkpoint['initial_energy_j']!=result.initial_energy or checkpoint['initial_mass_kg']!=result.initial_mass or abs(result.time-registry['continuation']['time_s'])>1e-12:raise ValueError('Persistent field budgets/clock mismatch')
  if abs(result.external-result.config['heater_w']*(result.time-result._initial_time))>1e-9*max(1,result.external):raise ValueError('Persistent heater work/clock mismatch')
  if not isinstance(checkpoint['receipts'],list) or len(checkpoint['receipts'])>64 or not isinstance(checkpoint['transfers'],list) or len(checkpoint['transfers'])>64:raise ValueError('Persistent field diagnostics exceed bounded history')
  for receipt in checkpoint['receipts']:
   if not isinstance(receipt,dict) or set(receipt)!={'dt_s','external_heat_j','energy_residual_j','mass_residual_kg'}:raise ValueError('Invalid persistent field receipt')
   duration=number(receipt['dt_s'],1e-15,.25);work=number(receipt['external_heat_j'],0,25)
   if abs(work-result.config['heater_w']*duration)>1e-10:raise ValueError('Field receipt heater work differs')
   for key in ('energy_residual_j','mass_residual_kg'):
    value=receipt[key]
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Nonfinite field receipt')
  matter_ids={r['matter_id'] for r in result.mapping}
  for transfer in checkpoint['transfers']:
   keys={'time_s','changed_owner_count','thermal_energy_residual_j','chemical_energy_residual_j','species_mass_residual_kg','matter_ids'}
   if not isinstance(transfer,dict) or set(transfer)!=keys:raise ValueError('Invalid persistent transfer receipt')
   number(transfer['time_s'],0,result.time)
   if type(transfer['changed_owner_count']) is not int or not 0<=transfer['changed_owner_count']<=len(matter_ids):raise ValueError('Invalid transfer owner count')
   ids=transfer['matter_ids']
   if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or len(ids)!=len(matter_ids) or set(ids)!=matter_ids:raise ValueError('Transfer persistent matter IDs differ')
   for key in keys-{'time_s','changed_owner_count','matter_ids'}:
    if type(transfer[key]) not in (int,float) or not math.isfinite(transfer[key]) or abs(transfer[key])>1e-8:raise ValueError('Invalid transfer conservation receipt')
  result.receipts=copy.deepcopy(checkpoint['receipts']);result.transfers=copy.deepcopy(checkpoint['transfers']);snapshot=result.snapshot()
  if abs(snapshot['audit']['energy_residual_j'])>1e-9*max(1,result.initial_energy) or abs(snapshot['audit']['mass_residual_kg'])>1e-12:raise ValueError('Persistent field conservation mismatch')
  return result
