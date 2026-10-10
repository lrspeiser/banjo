"""Actual coupled matter IDs/owner transitions retain native fields and clock."""
import copy,json,math,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cpu_coupled_world import CpuCoupledWorld
from thermal_matter_adapter import ThermalMatterAdapter
evidence=[]
for material in ('glass','oak','iron','ice'):
 world=CpuCoupledWorld(dict(material=material,ball_material=material,ball_mass_kg=.001,height_m=10.,dt_s=1/960,representation_policy='partitioned-flight'))
 field=ThermalMatterAdapter(world.registry.document(),dict(initial_temperature_k=260.,heater_w=2.,heater_body_id=3,reaction=False))
 assert len(field.cells)==len(world.eval.bodies)-1 and len(field.links)==12
 before=field.export_checkpoint();field.advance(world.d['dt_s']);heated=copy.deepcopy(field.cells)
 world.advance(1);field.rebind(world.registry.document());s=field.snapshot(world.eval.bodies)
 assert field.cells==heated and s['last_transfer']['changed_owner_count']==1
 assert s['time_s']==world.time and s['audit']['external_heat_j']==2*world.d['dt_s']
 assert abs(s['audit']['energy_residual_j'])<1e-8 and abs(s['audit']['mass_residual_kg'])<1e-12
 ids={r['matter_id'] for r in field.mapping};assert all(r['matter_id'] in ids and r['matter_id'].startswith(world.registry.world_id+'/') for r in s['fields'])
 assert all(r['position_m']==[float(x) for x in world.eval.bodies[r['body_id'],7:10]] for r in s['fields'])
 assert all(c[6]==c[7]==c[9]==0 for c in field.cells), 'moving bodies acquire no fuel/oxygen mass'
 saved=field.export_checkpoint();restored=ThermalMatterAdapter.restore(saved,world.registry.document());assert restored.export_checkpoint()==saved
 original=field.clone();field.advance(world.d['dt_s']);restored.advance(world.d['dt_s']);assert field.cells==restored.cells
 # A rejected ownership map/clock leaves EVERY canonical field byte/counter unchanged.
 field=original;unchanged=field.export_checkpoint()
 bad=world.registry.document();bad['continuation']['time_s']+=1
 try:field.rebind(bad);raise AssertionError('mismatched clock admitted')
 except ValueError:pass
 assert field.export_checkpoint()==unchanged
 bad=world.registry.document();objects=bad['continuation']['instances'];objects[-1]['matter_ids'][0]=objects[1]['matter_ids'][0]
 try:field.rebind(bad);raise AssertionError('duplicate matter admitted')
 except ValueError:pass
 assert field.export_checkpoint()==unchanged
 # Order permutation preserves each heterogeneous cell energy by ID, never averages it.
 permuted=world.registry.document();permuted['continuation']['instances'].reverse();old={r['matter_id']:copy.deepcopy(c) for r,c in zip(field.mapping,field.cells)}
 field.rebind(permuted);assert all(c==old[r['matter_id']] for r,c in zip(field.mapping,field.cells))
 reopened=ThermalMatterAdapter.restore(field.export_checkpoint(),permuted);assert reopened.export_checkpoint()==field.export_checkpoint()
 for key in ('time_s','external_heat_j','initial_energy_j'):
  bad=field.export_checkpoint();bad[key]+=1
  try:ThermalMatterAdapter.restore(bad,permuted);raise AssertionError('corrupted persistent account admitted')
  except ValueError:pass
 evidence.append(dict(material=material,matter_ids=[r['matter_id'] for r in s['fields']],dt_s=world.d['dt_s'],resolution_m=.01,external_heat_j=s['audit']['external_heat_j'],energy_residual_j=s['audit']['energy_residual_j'],species_mass_residual_kg=s['audit']['mass_residual_kg'],changed_owner_count=s['last_transfer']['changed_owner_count']))
# Free rigid primitive: no edges, heating proceeds independently of mechanical binding.
world=CpuCoupledWorld(dict(experiment='freefall',ball_material='iron',height_m=10.,representation_policy='partitioned-flight'))
field=ThermalMatterAdapter(world.registry.document(),dict(heater_body_id=1,heater_w=1.,initial_temperature_k=260.));cp=field.cells[0][0]*450
field.advance(.25);assert abs(field.observations()[0][0]-(260+.25/cp))<1e-10
initial=field.export_checkpoint();bad=field.clone();bad.cells[0][1]=bad.cells[0][0]*450*2999.999;bad.cells[0][14]=1000
before=bad.export_checkpoint()
try:bad.advance(1.);raise AssertionError('late native refusal missing')
except ValueError:pass
assert bad.export_checkpoint()==before
try:ThermalMatterAdapter(world.registry.document(),dict(heater_body_id=1,reaction=True));raise AssertionError('oxidative mass added to mechanics')
except ValueError:pass
print(json.dumps(dict(scope='genuine field state retained across actual coupled rigid-flight owner switch; no weakening/fracture transport',materials=evidence),indent=2))
