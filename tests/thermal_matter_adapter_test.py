"""Actual coupled matter IDs/owner transitions retain native fields and clock."""
import copy,json,math,sys,time
from pathlib import Path
import numpy as np
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
# Heat crosses a face only through its bonded part. Fully separated faces
# isolate the heated centre cell exactly; half-bonded faces carry half the
# authored conductance; the field's energy account closes either way.
world=CpuCoupledWorld(dict(material='glass',ball_material='iron',ball_mass_kg=.1,height_m=1.,dt_s=1/240,representation_policy='partitioned-flight'))
field=ThermalMatterAdapter(world.registry.document(),dict(initial_temperature_k=260.,heater_w=2.,heater_body_id=7))
authored=[link[2] for link in field.links];faces={(int(e[0]),int(e[1])) for e in world.eval.edges}
assert len(faces)==12 and all(g>0 for g in authored)
field.bond({face:.5 for face in faces});assert [link[2] for link in field.links]==[g*.5 for g in authored]
field.bond({face:0. for face in faces});assert all(link[2]==0 for link in field.links)
before=field.observations();field.advance(1.);after=field.observations()
centre=next(i for i,r in enumerate(field.mapping) if r['body_id']==7);mass=field.cells[centre][0]
for i,(t0,t1) in enumerate(zip(before,after)):
 if i==centre:assert abs(t1[0]-t0[0]-2/(mass*field.mapping[i]['thermal_law']['cs']))<1e-9,'isolated heater cell takes all the heat'
 else:assert t1[0]==t0[0],'no heat crosses a separated face'
assert abs(field.snapshot()['audit']['energy_residual_j'])<1e-9
field.bond({face:1. for face in faces});assert [link[2] for link in field.links]==authored
permuted=world.registry.document();permuted['continuation']['instances'].reverse()
field=ThermalMatterAdapter(world.registry.document(),dict(heater_body_id=7));field.bond({(3,4):.25});field.rebind(permuted)
k=next(i for i,(a,b,_) in enumerate(field.links) if {field.mapping[a]['body_id'],field.mapping[b]['body_id']}=={3,4})
assert field.links[k][2]==.25*field.bonded_links[k][2] and field.bonded_links[k][2]>0,'rebinding keeps each face its bonded fraction'
for bad in ({(3,4):1.5},{(3,4):-.1},{(3,11):1.},{(0,3):1.}):
 try:field.bond(bad);raise AssertionError('invalid bonded fraction admitted')
 except ValueError:pass
assert CpuCoupledWorld.bonded_fractions(world.eval.edges,np.zeros((len(world.eval.edges),32)))=={face:1. for face in faces}
damaged=np.zeros((len(world.eval.edges),32));damaged[[i for i,e in enumerate(world.eval.edges) if (int(e[0]),int(e[1]))==(3,4)][:2],5]=1.
assert CpuCoupledWorld.bonded_fractions(world.eval.edges,damaged)[(3,4)]==.5,'two of four broken sites leave half the face bonded'
print(json.dumps(dict(scope='genuine field state retained across actual coupled rigid-flight owner switch; conduction through each face in proportion to its bonded fraction',materials=evidence),indent=2))
