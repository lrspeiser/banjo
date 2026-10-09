import sys,time,json,builtins,statistics,hashlib
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'scripts'))
import cupy as cp, gpu_coupled_world as module
from gpu_coupled_world import GpuCoupledWorld,source_hash
rows=[]
for material in ('glass','oak','iron','ice'):
 w=GpuCoupledWorld(dict(material=material,height_m=.001,dt_s=1/240));e=w.eval
 # Warm CUDA linear/runtime allocations without changing the physical input.
 e.solve(1/960)
 calls=[];waits=[];linears=[];events=[];phase_events=[]
 original_eval=e.evaluate;original_linear=cp.linalg.solve;original_solve=e.solve
 def evaluate(*a,**kw):
  start=time.perf_counter();aevent=cp.cuda.Event();bevent=cp.cuda.Event();aevent.record();r=original_eval(*a,**kw);bevent.record();calls.append((time.perf_counter()-start,len(r['faults'])));events.append((aevent,bevent));return r
 def linear(*a,**kw):
  start=time.perf_counter();ae=cp.cuda.Event();be=cp.cuda.Event();ae.record();r=original_linear(*a,**kw);be.record();linears.append(time.perf_counter()-start);phase_events.append((ae,be));return r
 def scalar(kind,value):
  t=time.perf_counter();r=kind(value)
  if isinstance(value,cp.ndarray):waits.append((kind.__name__,time.perf_counter()-t))
  return r
 def solve(*a,**kw):
  module.float=lambda x:scalar(builtins.float,x);module.int=lambda x:scalar(builtins.int,x);module.bool=lambda x:scalar(builtins.bool,x)
  try:return original_solve(*a,**kw)
  finally:del module.float,module.int,module.bool
 e.evaluate=evaluate;cp.linalg.solve=linear;e.solve=solve
 start=time.perf_counter()
 try:
  for tick in range(10):s=w.advance(1)
 finally:
  cp.linalg.solve=original_linear;e.solve=original_solve
 cp.cuda.get_current_stream().synchronize();wall=time.perf_counter()-start
 row=dict(material=material,physical_time_s=s['time_s'],wall_s=wall,evaluate_calls=len(calls),evaluate_enqueue_s=sum(x[0] for x in calls),evaluate_cuda_s=sum(cp.cuda.get_elapsed_time(a,b)/1000 for a,b in events),linear_calls=len(linears),linear_host_s=sum(linears),linear_cuda_s=sum(cp.cuda.get_elapsed_time(a,b)/1000 for a,b in phase_events),scalar_sync_count=len(waits),scalar_sync_s=sum(x[1] for x in waits),performance=s['performance']);rows.append(row);print(row,flush=True)
Path('build/gpu-local-solve/profile.json').write_text(json.dumps(dict(source_sha256=source_hash(),instrumentation='Runtime observation wrappers; no equation or solver change. CUDA events add overhead; overlapping phase times are not additive.',rows=rows),indent=2),encoding='utf8')
