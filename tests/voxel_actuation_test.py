"""Native external-work, bounded admission and unloading integration checks."""
import argparse,json,math,subprocess,time
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('native');parser.add_argument('--results',type=Path)
args=parser.parse_args();records=[]
class World:
 def __init__(self,declaration):
  self.p=subprocess.Popen([args.native,'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  self.initial=self.call({'op':'create','declaration':declaration});self.state=self.initial
 def reply(self,command):
  self.p.stdin.write(json.dumps(command)+'\n');self.p.stdin.flush();return json.loads(self.p.stdout.readline())
 def call(self,command):
  r=self.reply(command);assert r['ok'],r.get('error');self.state=r['state'];return self.state
 def advance(self,seconds):
  ticks=round(seconds/self.state['dt_s']);assert ticks*self.state['dt_s']-seconds<1e-10
  while ticks:self.call({'op':'advance','steps':min(16,ticks)});ticks-=min(16,ticks)
  return self.state
 def force(self,a,object=2):return self.call({'op':'accelerate_object','object':object,'acceleration_m_s2':a})
 def close(self):self.p.stdin.close();self.p.wait()
def center(state,object=2):return next(o['center_m'] for o in state['objects'] if o['id']==object)
def save(record):
 records.append(record)
 if args.results:args.results.write_text(json.dumps(records),encoding='utf-8')
def physical_cells(state):return state['cells']
for material in ['glass','oak','iron']:
 w=World({'sheet':material,'ball':material,'face_law':'centered-log-gradient','gravity_m_s2':0,'height_m':10})
 try:
  before=w.state;commanded=w.force([2,10,0]);assert physical_cells(commanded)==physical_cells(before),'command assigns motion'
  state=w.advance(.1);ball=next(o for o in state['objects'] if o['id']==2);a=state['actuation'];mass=ball['mass_kg']
  for i,acceleration in enumerate([2,10,0]):
   assert abs(ball['velocity_m_s'][i]-acceleration*.1)<64*2**-23*max(1,abs(acceleration*.1)),'free-flight velocity oracle'
   assert abs(center(state)[i]-center(before)[i]-.5*acceleration*.1**2)<64*2**-23,'free-flight trajectory oracle'
   assert abs(a['impulse_n_s'][i]-mass*acceleration*.1)<1e-10,'declared impulse oracle'
  assert abs(a['work_j']-.5*mass*(2**2+10**2)*.1**2)<1e-5,'trajectory external work oracle'
  assert abs(state['diagnostics']['unclosed_energy_j'])<1e-4,'external input must not be unexplained energy'
  work=a['work_j'];impulse=a['impulse_n_s'];stopped=w.force([0,0,0]);assert physical_cells(stopped)==physical_cells(state),'release assigns motion'
  coast=w.advance(.1);assert coast['actuation']['work_j']==work and coast['actuation']['impulse_n_s']==impulse,'released actuator still contributes'
  for command in [{'op':'accelerate_object','object':3,'acceleration_m_s2':[0,20,0]},
                  {'op':'accelerate_object','object':True,'acceleration_m_s2':[0,20,0]},
                  {'op':'accelerate_object','object':2,'acceleration_m_s2':[0,31,0]},
                  {'op':'accelerate_object','object':2,'acceleration_m_s2':[0,20]},
                  {'op':'accelerate_object','object':2,'acceleration_m_s2':[0,'20',0]}]:
   r=w.reply(command);assert not r['ok'] and r['state']==coast,'invalid command mutated accepted state'
  for _ in range(30):w.force([0,0,0])
  accepted=w.state;r=w.reply({'op':'accelerate_object','object':2,'acceleration_m_s2':[0,0,0]})
  assert not r['ok'] and r['state']==accepted,'actuator command count is not bounded atomically'
  print(json.dumps({'oracle':material,'external_work_j':work,'energy_residual_j':state['diagnostics']['unclosed_energy_j'],
                    'force_phase_impulse_residual_n_s':state['actuation']['force_phase_impulse_residual_n_s']}),flush=True)
  save({'oracle':material,'before':before,'forced':state,'coast':coast})
 finally:w.close()
for declaration in [{'ball_enabled':False,'face_law':'centered-log-gradient'},{}]:
 w=World(declaration)
 try:
  r=w.reply({'op':'accelerate_object','object':2,'acceleration_m_s2':[0,20,0]})
  assert not r['ok'] and r['state']==w.initial,'unsupported actuator admission mutates world'
 finally:w.close()
for material,plastic in [('glass',False),('oak',False),('iron',False),('iron',True)]:
 d={'sheet':material,'ball':'iron','mass_kg':5,'height_m':1,'face_law':'centered-log-gradient','contact_law':'midpoint-block-friction'}
 if plastic:d['sheet_plasticity']=True
 start=time.perf_counter();w=World(d)
 try:
  loaded=w.advance(.6);w.force([0,20,0]);unloaded=w.advance(.4);w.force([0,0,0]);released=w.advance(.1)
  ball_bottom=min(c['position_m'][1]-sum(c['size_m'])/2 for c in released['cells'] if c['object']==2)
  sheet_top=max(c['position_m'][1]+sum(c['size_m'])/2 for c in released['cells'] if c['object']==1)
  assert ball_bottom>sheet_top+.01,'ball did not physically separate from sheet'
  assert released['diagnostics']['dynamic_mass_kg']==w.initial['diagnostics']['dynamic_mass_kg'],'unloading removed matter'
  rest=0
  if plastic:
   rest=max(abs(x) for h in released['plasticity']['history'] for x in h['plastic_rest'])
   assert rest>0 and released['plasticity']['yielded_connectors']>=loaded['plasticity']['yielded_connectors'],'unloading reset deformation history'
   assert released['plasticity']['plastic_work_j']>=loaded['plasticity']['plastic_work_j'],'unloading erased plastic work'
   inner_ids={c['id'] for c in w.initial['cells'] if c['object']==1 and abs(c['position_m'][0])<.1 and abs(c['position_m'][2])<.1}
   inner=[c for c in released['cells'] if c['id'] in inner_ids]
   assert sum(c['position_m'][1] for c in inner)/len(inner)<.501,'unloaded native metal surface has no retained downward deformation'
  dent=max(abs(c['position_m'][1]-.502) for c in released['cells'] if c['object']==1)
  print(json.dumps({'sheet':material,'plastic':plastic,'wall_s':time.perf_counter()-start,'external_work_j':released['actuation']['work_j'],
                    'unclosed_energy_j':released['diagnostics']['unclosed_energy_j'],'unloaded_displacement_m':dent,'rest_max':rest}),flush=True)
  save({'sheet':material,'plastic':plastic,'initial':w.initial,'loaded':loaded,'unloaded':unloaded,'released':released})
 finally:w.close()
print('PASS bounded native force, free-flight work/impulse, release, admission and matched material unloading; full continuum/contact accuracy remains open')
