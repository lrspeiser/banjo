"""Actual native mechanics/fields share matter, clocks and atomic continuation."""
import copy,json,math,sys,time
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cpu_coupled_world import CpuCoupledWorld
from object_registry import open_checkpoint,seal
from thermal_fields import MATERIALS

evidence=[]
for material in ('glass','oak','iron','ice'):
 raw=dict(experiment='freefall',ball_material=material,ball_mass_kg=.1,height_m=10.,dt_s=1/240,
          contact_resolution='phase-0.0625',representation_policy='partitioned-flight',pipeline='local-jacobian')
 heated=CpuCoupledWorld(raw|dict(thermal=dict(initial_temperature_k=260.,heater_w=2.,heater_body_id=1)))
 reference=CpuCoupledWorld(raw);started=time.perf_counter()
 while heated.time<2-1e-10:
  count=min(16,480-heated.ticks);heated.advance(count);reference.advance(count)
  assert np.array_equal(heated.eval.bodies,reference.eval.bodies),'unqualified temperature-dependent forces were introduced'
  assert np.array_equal(heated.eval.edges,reference.eval.edges)
  s=heated.snapshot();f=s['thermal_fields'];assert abs(f['time_s']-s['time_s'])<1e-12
  assert abs(f['audit']['energy_residual_j'])<1e-8 and abs(f['audit']['mass_residual_kg'])<1e-12
  for a in s['substep_accounts']:
   field=a['thermal_fields']['fields'][0];assert field['position_m']==a['poses_wxyz'][1][:3]
  ball_instance=next(instance for instance in heated.registry.binding_state()['instances'] if instance['body_ids']==[1])
  assert f['fields'][0]['matter_id']==ball_instance['matter_ids'][0]
  assert all(isinstance(matter,str) and matter in ball_instance['matter_ids'] for matter in f['last_transfer']['matter_ids'])
  # Independent combined total-energy account, including the existing native
  # storage and dissipative accounts exactly once and explicit heater work.
  d=s['diagnostics'];thermal_energy=math.fsum(cell['thermal_energy_j'] for cell in f['fields'])
  mechanical_account=d['mechanical_j']+d['material_stored_j']+d['contact_stored_j']+d['fracture_work_j']+d['plastic_work_j']+d['numerical_return_excess_j']
  combined_residual=mechanical_account+thermal_energy-heated.initial_energy-heated.fields.initial_energy-f['audit']['external_heat_j']
  assert abs(combined_residual)<1e-8,combined_residual
  assert abs(combined_residual-(d['global_energy_residual_j']+f['audit']['energy_residual_j']))<1e-9
 field=f['fields'][0];expected=260+2*heated.time/(.1*MATERIALS[material]['cs'])
 assert abs(field['temperature_k']-expected)<1e-9
 saved=heated.export_checkpoint();reopened=CpuCoupledWorld.from_checkpoint(saved)
 assert reopened.export_checkpoint()==saved,'native field history/clock/owner changed on exact reopen'
 bad=open_checkpoint(saved);bad['thermal_fields']['config']['heater_w']=3
 try:CpuCoupledWorld.from_checkpoint(seal(bad));raise AssertionError('field law edit admitted')
 except ValueError:pass
 assert heated.eval.bodies[1,15]>0,'full drop did not finish a physical rebound'
 evidence.append(dict(material=material,dt_s=raw['dt_s'],contact_phase_rad=.0625,ball_mass_kg=.1,height_m=10.,accepted_s=heated.time,paired_wall_s=time.perf_counter()-started,temperature_k=field['temperature_k'],field_energy_error_j=f['audit']['energy_residual_j'],mechanical_energy_error_j=s['diagnostics']['global_energy_residual_j'],combined_energy_error_j=combined_residual,rebound_velocity_y_m_s=float(heated.eval.bodies[1,15]),heater_work_j=f['audit']['external_heat_j']))

# Failure after actual heat advancement must roll back native mechanics, fields,
# registry, history and clock together; keep only the explicit stopped receipt.
w=CpuCoupledWorld(raw|dict(thermal=dict(heater_body_id=1)));before=w.export_checkpoint()
with patch.object(type(w.fields),'rebind',side_effect=MemoryError('late field publication allocation')):
 try:w.advance(1);raise AssertionError('injected late failure was ignored')
 except RuntimeError:pass
after=open_checkpoint(w.export_checkpoint());original=open_checkpoint(before)
for key in ('native','registry','thermal_fields','continuation','representation'):assert after[key]==original[key],key
assert w.snapshot()['rejected_candidate']['interval_rolled_back'] is True

# Ice may not silently become liquid while continuing as an unchanged rigid
# solid. This unsupported combination refuses and leaves accepted state intact.
w=CpuCoupledWorld(raw|dict(ball_material='ice',thermal=dict(initial_temperature_k=273.15,heater_w=100.,heater_body_id=1)))
before=w.export_checkpoint()
try:w.advance(1);raise AssertionError('unimplemented solid-to-flow transition admitted')
except RuntimeError as e:assert 'Solid-to-flow' in str(e)
after=open_checkpoint(w.export_checkpoint());original=open_checkpoint(before)
assert after['native']==original['native'] and after['thermal_fields']==original['thermal_fields']
print(json.dumps(dict(scope='shared native mechanics and retained thermal field; constant mechanical laws; no fracture transport or temperature weakening',materials=evidence,late_atomic_rollback=True,unsupported_phase_rollback=True),indent=2))
