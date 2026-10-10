"""Bounded native scalar field world; rendering never evolves physical state."""
import copy, ctypes, hashlib, json, math, os, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MATERIALS={
 'glass':dict(density=2500.,cs=840.,cl=840.,conductivity=1.,latent=0.),
 'oak':dict(density=700.,cs=1700.,cl=1700.,conductivity=.12,latent=0.),
 'iron':dict(density=7870.,cs=450.,cl=450.,conductivity=80.,latent=0.),
 'ice':dict(density=917.,cs=2100.,cl=4180.,conductivity=2.2,latent=334000.),
}
def library_path():
 p=os.environ.get('BANJO_THERMAL_FIELDS_LIBRARY')
 if p:return Path(p).resolve()
 candidates=[ROOT/'bin/libbanjo_thermal_fields.so',ROOT/'build/voxel-contact-audit/Release/banjo_thermal_fields.dll']
 for p in candidates:
  if p.is_file():return p
 raise ValueError('Native thermal field library unavailable; no visual fallback')
def source_hash():
 h=hashlib.sha256()
 for name in ('scripts/thermal_fields.py','scripts/thermal-field-worker.py','src/thermal/ThermalFieldApi.cpp','src/thermal/ThermalFieldApi.hpp','src/thermal/ThermalKernel.cpp','src/thermal/ThermalKernel.hpp','src/thermal/EnthalpyLaw.cpp','src/thermal/EnthalpyLaw.hpp'):
  h.update(name.encode());h.update((ROOT/name).read_bytes())
 return h.hexdigest()
def number(v,lo,hi):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Value outside bounded declaration')
 return float(v)
class ThermalFields:
 def __init__(self,declaration):
  if not isinstance(declaration,dict) or set(declaration)-{'material','initial_temperature_k','heater_w','heater_cell','oxygen_fraction','reaction','dt_s'}:raise ValueError('Unknown field declaration')
  self.declaration=dict(material='iron',initial_temperature_k=260.,heater_w=2.,heater_cell=0,oxygen_fraction=.015,reaction=False,dt_s=.05);self.declaration.update(declaration)
  d=self.declaration
  if d['material'] not in MATERIALS:raise ValueError('Unknown catalog properties')
  number(d['initial_temperature_k'],150,1200);number(d['heater_w'],0,100);number(d['dt_s'],.001,.25);number(d['oxygen_fraction'],0,.05)
  if type(d['heater_cell']) is not int or not 0<=d['heater_cell']<24 or type(d['reaction']) is not bool:raise ValueError('Invalid source/reaction declaration')
  if d['reaction'] and d['material']!='oak':raise ValueError('Only declared demonstration fuel composition has a reaction law; no name-only combustion')
  self.library=library_path();self.lib=ctypes.CDLL(str(self.library));ptr=ctypes.POINTER(ctypes.c_double)
  self.lib.banjo_thermal_field_step.argtypes=[ptr,ctypes.c_int,ptr,ctypes.c_int,ctypes.c_double,ptr,ptr];self.lib.banjo_thermal_field_step.restype=ctypes.c_int
  self.lib.banjo_thermal_field_observe.argtypes=[ptr,ctypes.c_int,ptr];self.lib.banjo_thermal_field_observe.restype=ctypes.c_int
  self.identity={'source_sha256':source_hash(),'binary_sha256':hashlib.sha256(self.library.read_bytes()).hexdigest()}
  p=MATERIALS[d['material']];mass=p['density']*1e-6;self.cells=[];self.edges=[]
  t=d['initial_temperature_k'];h=p['cs']*min(t,273.15) if p['latent'] else p['cs']*t
  if p['latent'] and t>273.15:h=p['cs']*273.15+p['latent']+p['cl']*(t-273.15)
  for i in range(24):
   fuel=mass*.9 if d['material']=='oak' else 0.;oxygen=mass*d['oxygen_fraction'] if fuel else 0.
   self.cells.append([mass,mass*h,p['cs'],p['cl'],273.15,p['latent'],fuel,oxygen,mass-fuel,0.,16e6 if fuel else 0.,.5 if fuel else 0.,600.,1.5,d['heater_w'] if i==d['heater_cell'] else 0.,float(d['reaction'])])
   x,z=i%6,i//6
   if x:self.edges.append([i-1,i,p['conductivity']*.01])
   if z:self.edges.append([i-6,i,p['conductivity']*.01])
  self.time=0.;self.external=0.;self.released=0.;self.elapsed=0.;self.initial_energy=sum(c[1]+c[6]*c[10] for c in self.cells);self.initial_mass=sum(sum(c[6:10]) for c in self.cells);self.accounts=[];self.failure=None
 def _array(self,values):return (ctypes.c_double*len(values))(*values)
 def observations(self):
  raw=self._array([v for c in self.cells for v in c]);out=(ctypes.c_double*48)()
  if self.lib.banjo_thermal_field_observe(raw,24,out):raise ValueError('Native temperature observation refused')
  return [[out[2*i],out[2*i+1]] for i in range(24)]
 def snapshot(self):
  obs=self.observations();return {'schema':'banjo.thermal-fields.v1','time_s':self.time,'declaration':copy.deepcopy(self.declaration),'implementation':self.identity,'solver_backend':'native-cpu-fields','cells':[dict(matter_id=f'field-cell-{i}',object_id='field-sheet',position_m=[(i%6-2.5)*.01,0,(i//6-1.5)*.01],size_m=.01,thermal_mass_kg=c[0],species_mass_kg=sum(c[6:10]),enthalpy_j=c[1],temperature_k=obs[i][0],liquid_fraction=obs[i][1],fuel_kg=c[6],oxygen_kg=c[7],inert_kg=c[8],products_kg=c[9]) for i,c in enumerate(self.cells)],'audit':{'external_heat_j':self.external,'converted_chemical_j':self.released,'total_energy_j':sum(c[1]+c[6]*c[10] for c in self.cells),'energy_residual_j':sum(c[1]+c[6]*c[10] for c in self.cells)-self.initial_energy-self.external,'mass_residual_kg':sum(sum(c[6:10]) for c in self.cells)-self.initial_mass,'calculation_wall_s':self.elapsed,'scope':'Fixed geometry, scalar heat/phase and closed local species only; no mechanical/flow coupling'},'accounts':copy.deepcopy(self.accounts[-32:]),'last_failure':self.failure}
 def advance(self,steps):
  if type(steps) is not int or not 1<=steps<=200:raise ValueError('Steps must be 1..200')
  saved=(copy.deepcopy(self.cells),self.time,self.external,self.released,self.elapsed,copy.deepcopy(self.accounts));started=time.perf_counter()
  try:
   edges=self._array([v for e in self.edges for v in e]);dt=self.declaration['dt_s']
   for _ in range(steps):
    raw=self._array([v for c in self.cells for v in c]);out=(ctypes.c_double*384)();receipt=(ctypes.c_double*8)()
    if self.lib.banjo_thermal_field_step(raw,24,edges,len(self.edges),dt,out,receipt):raise ValueError('Native field candidate refused: invalid state or temperature exceeds 3000 K; interval restored')
    self.cells=[list(out[i*16:(i+1)*16]) for i in range(24)];self.time+=dt;self.external+=receipt[2];self.released+=receipt[3]
    self.accounts.append(dict(dt_s=dt,external_heat_j=receipt[2],converted_chemical_j=receipt[3],energy_residual_j=receipt[6],mass_residual_kg=receipt[5]-receipt[4]))
   self.elapsed+=time.perf_counter()-started;self.failure=None;return self.snapshot()
  except Exception as e:
   self.cells,self.time,self.external,self.released,self.elapsed,self.accounts=saved;self.failure=str(e);raise
 def export_checkpoint(self):return copy.deepcopy(dict(schema='banjo.thermal-fields.checkpoint.v1',implementation=self.identity,declaration=self.declaration,cells=self.cells,time_s=self.time,external_heat_j=self.external,converted_chemical_j=self.released,initial_energy_j=self.initial_energy,initial_mass_kg=self.initial_mass))
 @classmethod
 def restore(cls,checkpoint):
  if not isinstance(checkpoint,dict) or set(checkpoint)!={'schema','implementation','declaration','cells','time_s','external_heat_j','converted_chemical_j','initial_energy_j','initial_mass_kg'} or checkpoint['schema']!='banjo.thermal-fields.checkpoint.v1':raise ValueError('Invalid field checkpoint')
  world=cls(checkpoint['declaration'])
  if checkpoint['implementation']!=world.identity:raise ValueError('Source/binary identity mismatch')
  cells=checkpoint['cells']
  if not isinstance(cells,list) or len(cells)!=24 or any(not isinstance(c,list) or len(c)!=16 for c in cells):raise ValueError('Invalid cell history')
  for c in cells:
   for v in c:number(v,0,1e10)
  for original,c in zip(world.cells,cells):
   if any(original[i]!=c[i] for i in (0,2,3,4,5,8,10,11,12,13,14,15)):raise ValueError('Checkpoint edits fixed material/composition inputs')
   consumed=original[6]-c[6]
   if not original[15] and consumed!=0:raise ValueError('Checkpoint consumes fuel without an active law')
   if consumed<0 or abs(c[7]-(original[7]-consumed*original[13]))>1e-12 or abs(c[9]-consumed*(1+original[13]))>1e-12:raise ValueError('Checkpoint species stoichiometry inconsistent')
  if checkpoint['initial_energy_j']!=world.initial_energy or checkpoint['initial_mass_kg']!=world.initial_mass:raise ValueError('Checkpoint reference budgets inconsistent')
  world.cells=copy.deepcopy(cells)
  for attr,key in [('time','time_s'),('external','external_heat_j'),('released','converted_chemical_j'),('initial_energy','initial_energy_j'),('initial_mass','initial_mass_kg')]:setattr(world,attr,number(checkpoint[key],0,1e12))
  snap=world.snapshot()
  expected_heat=world.declaration['heater_w']*world.time
  expected_chemical=sum((initial[6]-c[6])*initial[10] for initial,c in zip(cls(world.declaration).cells,world.cells))
  if abs(world.time/world.declaration['dt_s']-round(world.time/world.declaration['dt_s']))>1e-6:raise ValueError('Checkpoint clock is not a declared tick boundary')
  if abs(world.external-expected_heat)>1e-9*max(1,expected_heat):raise ValueError('Checkpoint heater work and clock inconsistent')
  if abs(world.released-expected_chemical)>1e-9*max(1,expected_chemical):raise ValueError('Checkpoint chemical conversion counter inconsistent')
  if abs(snap['audit']['energy_residual_j'])>1e-8*max(1,world.initial_energy) or abs(snap['audit']['mass_residual_kg'])>1e-12:raise ValueError('Checkpoint conservation account inconsistent')
  return world
