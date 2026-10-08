"""Production native path checks; no prerecorded reaction or renderer surrogate."""
import argparse,json,math,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--native',required=True);a=p.parse_args()
exe=Path(a.native).resolve();results=[]
def experiment(declaration,duration):
 proc=subprocess.Popen([str(exe),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
 def request(value):
  proc.stdin.write(json.dumps(value)+'\n');proc.stdin.flush();reply=json.loads(proc.stdout.readline());assert reply['ok'],reply.get('error');return reply['state']
 try:
  first=request({'op':'create','declaration':declaration});state=first;ids={c['id']:c['mass_kg'] for c in first['cells']};start=time.monotonic();peak=0
  while state['time_s']<duration-1e-9:
   state=request({'op':'advance','steps':min(16,max(1,round((duration-state['time_s'])/state['dt_s'])))})
   assert {c['id']:c['mass_kg'] for c in state['cells']}==ids,'created/deleted/reweighted voxels'
   assert state['diagnostics']['unclosed_energy_j']<=.10001,'unbudgeted energy creation'
   assert all(math.isfinite(x) for c in state['cells'] for k in ['position_m','velocity_m_s','spin_rad_s'] for x in c[k])
   peak=max(peak,state['diagnostics']['kinetic_j'])
   if state['time_s']<1 and len(state['cells'])==len(first['cells']) and state['objects'][1]['cells']:
    t=state['time_s'];assert abs(state['objects'][1]['velocity_m_s'][1]+9.81*t)<.002,'freefall velocity'
    assert abs(state['objects'][1]['center_m'][1]-(first['objects'][1]['center_m'][1]-.5*9.81*t*t))<.006,'freefall trajectory'
  assert abs(state['time_s']-duration)<1e-8
  result={'declaration':declaration,'time_s':state['time_s'],'wall_s':time.monotonic()-start,'objects':state['objects'],'diagnostics':state['diagnostics'],'substeps':state['substeps'],'rejected_trials':state['rejected_trials']};results.append(result);print(json.dumps(result),flush=True)
  return first,state
 finally:proc.terminate();proc.wait(timeout=5)
for material in ['glass','oak','iron','ice']:
 before,after=experiment({'sheet':material},2)
 sheet=after['objects'][0]
 if material in ['glass','ice']:
  assert sheet['pieces']>1 and sheet['broken_faces']>0,'did not fracture'
  assert sheet['max_travel_m']>.15,'no visible constituent movement'
  assert after['objects'][1]['center_m'][1]<.5,'ball did not pass through sheet plane'
 else:assert sheet['pieces']==1 and sheet['broken_faces']==0,'unsupported brittle law substituted'
 assert sheet['max_travel_m']<5,'unphysical blowup'
for declaration in [{'sheet':'glass','ball_enabled':False},{'sheet':'glass','offset_x_m':.8}]:
 _,after=experiment(declaration,1.5)
 assert after['objects'][0]['broken_faces']==0,'rest/missed drop fractured sheet'
for declaration in [{'sheet':'glass','ball':'ice'},{'sheet':'glass','ball':'aluminum'},{'sheet':'glass','ball':'ceramic'},{'sheet':'glass','resolution':12},{'sheet':'glass','resolution':16}]:
 before,after=experiment(declaration,1.5)
 assert after['objects'][0]['broken_faces']>0,'changed experiment failed to break sheet'
 assert after['objects'][0]['max_travel_m']>.03,'fracture did not move voxels'
assert all(r['diagnostics']['dynamic_mass_kg']>0 for r in results)
# Glass ball is a retained qualification failure, not an advertised working choice.
proc=subprocess.Popen([str(exe),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
try:
 def raw(command):
  proc.stdin.write(json.dumps(command)+'\n');proc.stdin.flush();return json.loads(proc.stdout.readline())
 reply=raw({'op':'create','declaration':{'ball':'glass'}})
 for i in range(90):
  reply=raw({'op':'advance','steps':16})
  if not reply['ok']:break
 assert not reply['ok'] and 'energy gate refused' in reply['error'],'retained glass-ball failure unexpectedly changed; requalify before advertising'
 assert 1.4<reply['state']['time_s']<1.5
 assert raw({'op':'snapshot'})['state']==reply['state'],'refusal did not retain accepted state'
 print('KNOWN BLOCKED: glass ball reaches impact then refuses native energy increase; retained state verified',flush=True)
finally:proc.terminate();proc.wait(timeout=5)
print('PASS native voxel world: 11 completed comparative/control/refinement experiments + retained glass-ball refusal; realism/convergence unqualified',flush=True)
