"""Whole-field analytic, convergence, identity, closed-species and rollback controls."""
import copy,json,sys,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from thermal_fields import ThermalFields,MATERIALS
def exact_network(world,t):
 c=world.cells[0][0]*world.cells[0][2];matrix=np.zeros((24,24));power=np.array([a[14] for a in world.cells]);initial=np.array([a[1]/c for a in world.cells])
 for a,b,g in world.edges:
  matrix[a,a]+=g/c;matrix[b,b]+=g/c;matrix[a,b]-=g/c;matrix[b,a]-=g/c
 eigen,v=np.linalg.eigh(matrix);load=v.T@(power/c);a=v.T@initial
 decay=np.exp(-eigen*t);integral=np.array([t if abs(x)<1e-12 else -np.expm1(-x*t)/x for x in eigen])
 return v@(a*decay+load*integral)
evidence=[]
for material in MATERIALS:
 params=dict(material=material,initial_temperature_k=260.,heater_w=2.,dt_s=.025)
 w=ThermalFields(params);started=time.perf_counter();w.advance(200);elapsed=time.perf_counter()-started;s=w.snapshot()
 assert abs(s['audit']['energy_residual_j'])<1e-7 and abs(s['audit']['mass_residual_kg'])<1e-12
 checkpoint=w.export_checkpoint();restored=ThermalFields.restore(checkpoint);assert restored.export_checkpoint()==checkpoint
 w.advance(10);restored.advance(10);assert restored.export_checkpoint()==w.export_checkpoint()
 corrupted=copy.deepcopy(checkpoint);corrupted['cells'][0][2]*=2
 try:ThermalFields.restore(corrupted);raise AssertionError('edited constitutive property admitted')
 except ValueError:pass
 for key in ('time_s','converted_chemical_j','external_heat_j'):
  corrupted=copy.deepcopy(checkpoint);corrupted[key]+=1
  try:ThermalFields.restore(corrupted);raise AssertionError('edited clock/work/reaction counter admitted')
  except ValueError:pass
 evidence.append(dict(material=material,dt_s=.025,resolution_m=.01,cells=24,physical_s=s['time_s'],wall_s=elapsed,mass_per_cell_kg=s['cells'][0]['thermal_mass_kg'],temperature_min_k=min(c['temperature_k'] for c in s['cells']),temperature_max_k=max(c['temperature_k'] for c in s['cells']),**s['audit']))
 if params['initial_temperature_k'] < 273.15: # all controls remain below ice's latent plateau
  errors=[]
  for h in (.02,.01,.005):
   world=ThermalFields(dict(params,dt_s=h));oracle=exact_network(world,2.)
   for _ in range(round(2/h)//100):world.advance(100)
   actual=np.array([c['temperature_k'] for c in world.snapshot()['cells']]);errors.append(float(np.max(np.abs(actual-oracle))))
  assert errors[2]<errors[1]<errors[0],(material,errors)
  evidence[-1]['network_common_time_error_k']=errors
# Phase plateau and finite latent budget across the graph (no flowing geometry).
ice=ThermalFields(dict(material='ice',initial_temperature_k=273.15,heater_w=2.,dt_s=.05));ice.advance(200);s=ice.snapshot()
assert max(c['liquid_fraction'] for c in s['cells'])>0
assert max(abs(c['temperature_k']-273.15) for c in s['cells'])<1e-12
latent=sum(c['thermal_mass_kg']*334000*c['liquid_fraction'] for c in s['cells']);assert abs(latent-20)<1e-8
# Independent closed first-order fuel consumption before oxygen exhaustion.
fuel=ThermalFields(dict(material='oak',initial_temperature_k=650,heater_w=0.,oxygen_fraction=.05,reaction=True,dt_s=.001));initial=fuel.cells[0][6];fuel.advance(1);s=fuel.snapshot();consumed=initial*(1-np.exp(-.5*.001))
assert abs(s['cells'][0]['fuel_kg']-(initial-consumed))<1e-15
assert abs(s['cells'][0]['oxygen_kg']-(.0007*.05-consumed*1.5))<1e-15
assert abs(s['audit']['converted_chemical_j']-24*consumed*16e6)<1e-8
fuel.advance(200);before=fuel.export_checkpoint();fuel.advance(200);s=fuel.snapshot()
assert all(c['oxygen_kg']<1e-15 for c in s['cells'])
assert abs(s['audit']['mass_residual_kg'])<1e-12 and abs(s['audit']['energy_residual_j'])<1e-7
# Arbitrary heater location: actual temperature threshold determines which
# cell reacts. Neighbor cells remain unreacted; no predetermined burn pattern.
for source in (0,17):
 local=ThermalFields(dict(material='oak',initial_temperature_k=550,heater_w=20.,heater_cell=source,reaction=True,dt_s=.05))
 local.advance(200);local.advance(200);observed=local.snapshot()
 assert observed['cells'][source]['temperature_k']>600 and observed['cells'][source]['products_kg']>0
 assert all(c['products_kg']==0 and c['temperature_k']<600 for i,c in enumerate(observed['cells']) if i!=source)
 assert abs(observed['audit']['converted_chemical_j']-112.)<1e-6
 assert abs(observed['audit']['energy_residual_j'])<1e-7 and abs(observed['audit']['mass_residual_kg'])<1e-12
# Whole-interval rollback after earlier private steps succeeded.
refusal=ThermalFields(dict(material='oak',initial_temperature_k=2999-1800,heater_w=100.,dt_s=.25))
before=refusal.export_checkpoint()
try:refusal.advance(200);raise AssertionError('temperature guard not reached')
except ValueError:pass
assert refusal.export_checkpoint()==before
for d in ({'material':'glass','reaction':True},{'heater_w':float('nan')},{'dt_s':True},{'surprise':1}):
 try:ThermalFields(d);raise AssertionError('malformed declaration accepted')
 except ValueError:pass
print(json.dumps(dict(scope='native scalar field CPU reference; fixed geometry; no mechanical coupling',materials=evidence,phase_latent_j=latent,chemical_species_closed=True,atomic_rollback=True),indent=2))
