"""Local, bounded native voxel world. No old website routes or simulation cache."""
import os,sys
from types import SimpleNamespace
import argparse, bz2, copy, gzip, hashlib, io, json, queue, struct, subprocess, threading, time, uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'playground'))
# Its own folder too, for when another program loads this file as a module.
if str(ROOT/'scripts') not in sys.path:sys.path.insert(1,str(ROOT/'scripts'))
import access_gate
from urllib.parse import urlsplit
ASSETS={'/':'client/voxel-lab/index.html','/world.js':'client/voxel-lab/world.js','/playback.mjs':'client/voxel-lab/playback.mjs','/style.css':'client/voxel-lab/style.css','/three.module.js':'playground/vendor/three.module.js','/three.core.js':'playground/vendor/three.core.js','/gpu':'client/voxel-lab/gpu.html','/gpu.js':'client/voxel-lab/gpu.js','/gpu.css':'client/voxel-lab/gpu.css','/materials':'client/voxel-lab/materials.html','/materials.js':'client/voxel-lab/materials.js','/materials.css':'client/voxel-lab/materials.css'}
ASSETS['/native']='client/voxel-lab/index.html'
ASSETS['/scene-actions.css']='client/voxel-lab/scene-actions.css'
ASSETS.update({'/coupled':'client/voxel-lab/coupled.html','/coupled.js':'client/voxel-lab/coupled.js'})
ASSETS['/scene-session.mjs']='client/voxel-lab/scene-session.mjs'
ASSETS.update({'/coupled-view.mjs':'client/voxel-lab/coupled-view.mjs','/coupled.css':'client/voxel-lab/coupled.css'})
ASSETS.update({'/representations':'client/voxel-lab/representations.html','/representations.js':'client/voxel-lab/representations.js'})
for route,stem in (('mechanisms','mechanisms'),('flow','flowing-matter'),('thermal-fields','thermal-fields')):
 ASSETS['/'+route]='client/voxel-lab/'+stem+'.html'
 for ext in ('js','css'):ASSETS['/'+stem+'.'+ext]='client/voxel-lab/'+stem+'.'+ext
ASSETS['/mechanisms-view.mjs']='client/voxel-lab/mechanisms-view.mjs'
ASSETS['/flow-view.mjs']='client/voxel-lab/flow-view.mjs'
# The machine: one live engine world built from general parts (machine_world.py).
ASSETS.update({'/machine':'client/voxel-lab/machine.html','/machine.js':'client/voxel-lab/machine.js','/machine.css':'client/voxel-lab/machine.css',
 '/machine-view.mjs':'client/voxel-lab/machine-view.mjs','/machine-default.json':'client/voxel-lab/machine-default.json'})
# The puzzles: the same page, a level at a time (machine_game.py).
ASSETS['/play']='client/voxel-lab/machine.html'

class SessionExpired(ValueError):pass

# Bound disk use while retaining every accepted microstep of the two-second
# coupled experiment. The old 32 MB bound stopped a 10 m drop before contact.
JOURNAL_COMPRESSED_LIMIT=128_000_000
JOURNAL_ENCODED_LIMIT=1_024_000_000

def same_record(previous,current):
 if type(previous) is not type(current):return False
 if isinstance(current,float):return struct.pack('!d',previous)==struct.pack('!d',current)
 if isinstance(current,dict):return previous.keys()==current.keys() and all(same_record(previous[k],v) for k,v in current.items())
 if isinstance(current,list):return len(previous)==len(current) and all(same_record(a,b) for a,b in zip(previous,current))
 return previous==current

def record_patch(previous,current):
 # Exact replacements, never rounded numeric differences. Small coordinate
 # arrays replace together; large cell/event arrays retain unchanged fields.
 if type(previous) is not type(current):return {'r':current}
 if isinstance(current,dict):
  changed={k:record_patch(previous[k],v) if k in previous else {'r':v} for k,v in current.items() if k not in previous or not same_record(previous[k],v)}
  return {'d':changed,'x':[k for k in previous if k not in current]}
 if isinstance(current,list) and len(current)>4 and len(previous)==len(current):
  return {'a':{str(i):record_patch(a,b) for i,(a,b) in enumerate(zip(previous,current)) if not same_record(a,b)}}
 return {'r':current}

def apply_record_patch(previous,patch):
 if 'r' in patch:return patch['r']
 if 'd' in patch:
  result=dict(previous)
  for k in patch['x']:del result[k]
  for k,v in patch['d'].items():result[k]=apply_record_patch(result.get(k),v)
  return result
 result=list(previous)
 for i,v in patch['a'].items():result[int(i)]=apply_record_patch(result[int(i)],v)
 return result
def repository_state():
 try:
  revision=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True,timeout=3).strip()
  dirty=bool(subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain'],text=True,timeout=3).strip())
  return revision,dirty
 except (OSError,subprocess.SubprocessError):
  receipt=ROOT/'bin/build-receipt.json'
  try:return json.loads(receipt.read_text()).get('revision'),False
  except (OSError,ValueError):return None,None
class Session:
 def __init__(self,native,logs,checkpoint=None,worker_command=None,backend=None):
  self.backend=backend or ('gpu' if worker_command else 'cpu')
  self.worker_stderr=None
  if worker_command:
   self.worker_stderr=(logs/(uuid.uuid4().hex+'.worker.stderr.log')).open('w',encoding='utf8')
  self.proc=subprocess.Popen(worker_command or [str(native),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.worker_stderr or subprocess.DEVNULL,text=True,bufsize=1)
  self.output=queue.Queue(maxsize=2);self.lock=threading.Lock();self.record_lock=threading.Lock();self.last=time.monotonic();self.path=logs/(uuid.uuid4().hex+'.jsonl.bz2');self.bytes=0;self.uncompressed_bytes=0
  self.previous_record=None
  self.condition=threading.Condition();self.closed=False;self.native_failure=None;self.response_timeout_s=120. if worker_command else 25.;self.playing=False;self.calculating=False;self.latest=None;self.current=None;self.frame_id=0
  self.target_ticks=0;self.started=0.;self.started_time=0.;self.elapsed_s=0.;self.batch_cost_s=.001;self.max_batch_s=0.;self.pending_commands=[];self.last_publish=0.
  self.batch_samples=deque(maxlen=256);self.current_at=0.;self.latest_at=0.
  def reader():
   for line in self.proc.stdout:self.output.put(line)
   self.output.put(None)
  threading.Thread(target=reader,daemon=True).start()
  self.write({'native_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),'backend':self.backend,'worker_command':worker_command,'assets':{k:hashlib.sha256((ROOT/v).read_bytes()).hexdigest() for k,v in ASSETS.items()},'checkpoint':checkpoint})
  threading.Thread(target=self.simulate,daemon=True).start()
 def write(self,data):
  with self.record_lock:
   stored=data if self.previous_record is None else {'record_codec':'banjo.exact-replacements.v1','patch':record_patch(self.previous_record,data)}
   # Independent completed members persist each record even after a crash.
   # The 100 KB bzip2 block retains repeated fields in large native rows that
   # exceed gzip's 32 KB dictionary; numbers and all published poses stay exact.
   row=(json.dumps(stored,separators=(',',':'))+'\n').encode('utf8');compressed=bz2.compress(row,compresslevel=1)
   if self.bytes+len(compressed)>JOURNAL_COMPRESSED_LIMIT or self.uncompressed_bytes+len(row)>JOURNAL_ENCODED_LIMIT:raise ValueError('Session record limit reached; reset to continue')
   with self.path.open('ab') as f:f.write(compressed)
   self.bytes+=len(compressed);self.uncompressed_bytes+=len(row)
   self.previous_record=copy.deepcopy(data)
 def iter_log(self):
  # Snapshot at most the bounded compressed journal. Expand one exact
  # record at a time, so downloads need not allocate the whole replay history.
  with self.record_lock:data=self.path.read_bytes()
  previous=None
  archive=bz2.BZ2File(io.BytesIO(data),'rb') if data.startswith(b'BZh') else gzip.GzipFile(fileobj=io.BytesIO(data))
  with archive:
   for line in archive:
    row=json.loads(line)
    previous=apply_record_patch(previous,row['patch']) if row.get('record_codec')=='banjo.exact-replacements.v1' else row
    yield (json.dumps(previous,separators=(',',':'))+'\n').encode('utf8')
 def read_log(self):
  # Small inspection/test helper; production download uses iter_log directly.
  parts=[];size=0
  for row in self.iter_log():
   size+=len(row)
   if size>256_000_000:raise ValueError('Expanded record requires streaming download')
   parts.append(row)
  return b''.join(parts)
 def call(self,command,record=True):
  with self.lock:
   if self.native_failure:raise ValueError(self.native_failure['error'])
   self.last=time.monotonic();started=self.last
   try:
    self.proc.stdin.write(json.dumps(command)+'\n');self.proc.stdin.flush()
    line=self.output.get(timeout=self.response_timeout_s)
   except queue.Empty:return self.delivery_failed(command,started,'timeout',f'Native response exceeded {self.response_timeout_s:g} seconds. Last delivered scene retained; reset to continue.')
   except OSError:return self.delivery_failed(command,started,'pipe_closed','Native response pipe closed. Last delivered scene retained; reset to continue.')
   if line is None:return self.delivery_failed(command,started,'process_stopped','Native process stopped. Last delivered scene retained; reset to continue.')
   try:reply=json.loads(line)
   except ValueError:return self.delivery_failed(command,started,'invalid_response','Invalid native response. Last delivered scene retained; reset to continue.')
   if record:self.write({'request':command,'response':reply})
   return reply
 def stop_native(self):
  # This session owns the process. Stopping delivery never adjusts physics.
  if self.proc.poll() is None:
   self.proc.terminate()
   try:self.proc.wait(timeout=2)
   except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=2)
 def delivery_failed(self,command,started,reason,error):
  self.stop_native()
  with self.condition:
   # Persist completed commands first. The unanswered request is separate and
   # must never appear among accepted replay steps or generate a new pose.
   if self.pending_commands:self.publish(self.current,record=True)
   detail={'reason':reason,'request':command,'response_timeout_s':self.response_timeout_s,'elapsed_s':time.monotonic()-started,
           'last_delivered_time_s':self.current['state']['time_s'] if self.current and 'state' in self.current else None,
           'candidate_available':False,'unfinished_request':True}
   reply=dict(self.current or {},ok=False,error=error,delivery_failure=detail)
   self.native_failure=reply
   self.write({'request':command,'response':reply,'delivery':detail})
   return reply
 def metrics(self):
  now=time.monotonic();elapsed=max(0.,now-self.started) if self.started and (self.playing or self.calculating) else self.elapsed_s
  physical=max(0.,self.current['state']['time_s']-self.started_time) if self.current and self.started else 0.
  ordered=sorted(self.batch_samples);p95=ordered[max(0,(95*len(ordered)+99)//100-1)] if ordered else 0.
  return {'running':self.playing,'calculating':self.calculating,'realtime_ratio':physical/elapsed if elapsed else 0.,'wall_s':elapsed,
          'max_native_batch_ms':self.max_batch_s*1000,'native_batch_budget_ms':1000/30 if self.backend=='gpu' else 8,'frame_hz_target':30,'buffered_frames':1,'backend':self.backend,
          'native_batch_p95_ms':p95*1000,'batch_sample_count':len(ordered),'batch_sample_limit':256,
          'published_state_age_ms':max(0.,now-self.latest_at)*1000 if self.latest_at else 0.,
          'current_state_age_ms':max(0.,now-self.current_at)*1000 if self.current_at else 0.,
          'journal_compressed_bytes':self.bytes,'journal_uncompressed_bytes':self.uncompressed_bytes,
          'physics_changed':False,'status':'native stopped' if self.native_failure else 'running' if self.playing else 'pausing' if self.calculating else 'paused'}
 def publish(self,reply,record=False):
  # condition held by the caller. Every published pose is a native accepted
  # state; intermediate calls are retained as an exact replay command batch.
  if record:
   self.write({'request':{'op':'advance_batch','steps':self.pending_commands},'response':reply,'stream':self.metrics()})
  self.pending_commands=[];self.latest=self.current=reply;self.frame_id+=1;self.last_publish=time.monotonic();self.latest_at=self.current_at or self.last_publish;self.condition.notify_all()
 def manual(self,command):
  with self.condition:
   if self.closed:raise ValueError('Session closed')
   if self.playing or self.calculating:raise ValueError('Pause and wait for the current native batch before stepping')
   self.calculating=True
  try:
   reply=self.call(command)
   with self.condition:
    if command.get('op')!='export' and (reply['ok'] or command.get('op')!='accelerate_object' or 'delivery_failure' in reply):
     if 'delivery_failure' not in reply:self.current_at=time.monotonic()
     self.publish(reply)
  finally:
   with self.condition:self.calculating=False;self.condition.notify_all()
  with self.condition:return dict(reply,frame_id=self.frame_id,pipeline=self.metrics())
 def play(self,running,target):
  with self.condition:
   if self.closed or not self.latest:raise ValueError('Session unavailable')
   if running:
    if self.calculating and not self.playing:raise ValueError('Current native batch is still finishing')
    if not self.latest['ok']:raise ValueError(self.latest['error'] if self.native_failure else 'Native gate refused; reset to continue')
    state=self.current['state'];dt=state['dt_s']
    if state.get('controlled_loading'):raise ValueError('Controlled material loading has no dynamics clock; use Apply or Unload')
    limit=4 if 'actuation' in state else 2
    if type(target) not in (int,float) or not 0<target<=limit:raise ValueError(f'Target time must be within {limit} physical seconds')
    ticks=round(target/dt)
    if abs(ticks*dt-target)>1e-8 or ticks<=state['ticks']:raise ValueError('Target must be a later native tick boundary')
    if not self.playing:self.started=time.monotonic();self.started_time=state['time_s'];self.elapsed_s=0.;self.max_batch_s=0.;self.batch_samples.clear()
    self.target_ticks=ticks
   elif self.playing or self.calculating:self.elapsed_s=max(0.,time.monotonic()-self.started)
   self.playing=running;self.condition.notify_all()
   if not running and not self.calculating and self.pending_commands:self.publish(self.current,record=True)
   self.write({'control':{'op':'play','running':running,'target_time_s':target},'frame_id':self.frame_id,'pipeline':self.metrics()})
   return dict(self.latest,frame_id=self.frame_id,pipeline=self.metrics())
 def frame(self,after,wait_ms):
  with self.condition:
   if self.closed:raise ValueError('Session closed')
   self.condition.wait_for(lambda:self.closed or self.frame_id>after or not(self.playing or self.calculating),timeout=wait_ms/1000)
   if self.closed:raise ValueError('Session closed')
   if self.frame_id>after:return dict(self.latest,frame_id=self.frame_id,pipeline=self.metrics())
   reply={'ok':self.latest['ok'],'frame_id':self.frame_id,'pipeline':self.metrics()}
   if not reply['ok']:
    reply['error']=self.latest['error']
    if 'delivery_failure' in self.latest:reply['delivery_failure']=self.latest['delivery_failure']
   return reply
 def simulate(self):
  while True:
   with self.condition:
    self.condition.wait_for(lambda:self.closed or (self.playing and not self.calculating))
    if self.closed:return
    state=self.current['state']
    # Bound lookahead during fast freefall; never alter native dt or laws to
    # catch up. Slow impacts naturally report less than 1x physical speed.
    ahead=state['time_s']-self.started_time-(time.monotonic()-self.started)
    if ahead>.03:
     self.condition.wait(timeout=min(.03,ahead-.03));continue
    # The CUDA graph schedule uses a fixed resident batch. Adaptive native CPU
    # batch sizes would repeatedly capture new graphs and lose GPU throughput.
    batch=32 if self.backend=='gpu' else min(16,max(1,int(.008/max(.0001,self.batch_cost_s))))
    steps=min(batch,self.target_ticks-state['ticks'])
    if steps<=0:self.playing=False;self.condition.notify_all();continue
    self.calculating=True
   start=time.monotonic()
   try:
    reply=self.call({'op':'advance','steps':steps},record=self.backend in ('gpu','cpu-coupled'));cost=time.monotonic()-start
    with self.condition:
     self.calculating=False;self.current=reply;self.elapsed_s=max(0.,time.monotonic()-self.started);self.batch_cost_s=.5*self.batch_cost_s+.5*cost/steps;self.max_batch_s=max(self.max_batch_s,cost)
     if 'delivery_failure' not in reply:self.current_at=time.monotonic();self.pending_commands.append(steps)
     self.batch_samples.append(cost)
     if not reply['ok'] or reply['state']['ticks']>=self.target_ticks:self.playing=False
     # Keep only the latest frame in memory. Publish at most 30 Hz plus an
     # immediate final/pause/failure frame; no accumulating playback queue.
     if not self.playing or time.monotonic()-self.last_publish>=1/30:self.publish(reply,record='delivery_failure' not in reply)
     self.condition.notify_all()
   except (ValueError,OSError,TypeError,KeyError) as error:
    with self.condition:
     self.calculating=False;self.playing=False
     self.publish(dict(self.current,ok=False,error=str(error)));self.condition.notify_all()
 def close(self):
  with self.condition:self.closed=True;self.playing=False;self.condition.notify_all()
  self.stop_native()
  if self.worker_stderr:self.worker_stderr.close()
class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,native,logs,checkpoint_path=None,gpu_python=None,cpu_library=None,password=None,public_host=None):
  refusal=access_gate.refusal(address[0],password)
  if refusal:raise ValueError(refusal)
  self.app=SimpleNamespace(password=password,public_host=public_host,sessions=set(),login_destination='/machine')
  super().__init__(address,Handler);self.native=native;self.logs=logs;logs.mkdir(parents=True,exist_ok=True);self.sessions={};self.lock=threading.Lock()
  self.checkpoint_path=checkpoint_path or ROOT/'client/voxel-lab/checkpoint.json';self.started_revision,_=repository_state()
  self.cpu_library=cpu_library
  if cpu_library:os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(cpu_library)
  self.field_libraries={}
  for key,stem,env in (('mechanisms','banjo_mechanisms_cpu','BANJO_MECHANISMS_LIBRARY'),('flow','banjo_flow_cpu','BANJO_FLOW_LIBRARY'),('thermal-fields','banjo_thermal_fields','BANJO_THERMAL_FIELDS_LIBRARY')):
   candidate=Path(os.environ[env]) if os.environ.get(env) else (cpu_library.parent/((stem+'.dll') if os.name=='nt' else ('lib'+stem+'.so'))) if cpu_library else None
   self.field_libraries[key]=candidate if candidate and candidate.is_file() else None
   if self.field_libraries[key]:os.environ[env]=str(candidate)
  self.field_busy=threading.BoundedSemaphore(1)
  self.gpu_python=gpu_python;self.representation_busy=threading.BoundedSemaphore(1)
  from machine_world import MachineHost,engine_path
  self.machines=MachineHost(engine_path(native),logs/'machines');self.chat_busy=threading.BoundedSemaphore(2)
 def checkpoint_status(self):
  try:
   checkpoint=json.loads(self.checkpoint_path.read_text(encoding='utf8'))
   if not isinstance(checkpoint,dict):raise ValueError('Invalid checkpoint')
  except (ValueError,OSError):checkpoint={}
  revision,dirty=repository_state();actual=hashlib.sha256(self.native.read_bytes()).hexdigest()
  try:receipt=json.loads((ROOT/'bin/build-receipt.json').read_text())
  except (OSError,ValueError):receipt={}
  gpu_hash=hashlib.sha256((ROOT/'scripts/gpu_contact_world.py').read_bytes()).hexdigest() if self.gpu_python else None
  worker_hash=hashlib.sha256((ROOT/'scripts/gpu-contact-worker.py').read_bytes()).hexdigest() if self.gpu_python else None
  physx_hash=hashlib.sha256((ROOT/'scripts/physx_contact_world.py').read_bytes()).hexdigest() if self.gpu_python else None
  material_hash=None
  coupled_hash=None
  if self.gpu_python:
   h=hashlib.sha256()
   for name in ('scripts/coupled_representations.py','scripts/coupled_solver.py','scripts/coupled_world.py','scripts/gpu_coupled_world.py','scripts/gpu_linear_solve.py','scripts/gpu_representations.py','scripts/object_registry.py','src/physics/FiniteFrameKernel.hpp','src/physics/CohesiveInterfaceKernel.hpp','src/material/ConnectorModeKernel.hpp','src/physics/MaterialHistoryKernel.hpp','src/physics/NormalComplianceKernel.hpp','src/physics/CoupledGpuKernel.hpp','src/physics/CoupledFlightKernel.hpp','client/voxel-lab/material-laws.json'):
    h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes())
   coupled_hash=h.hexdigest()
   h=hashlib.sha256()
   for name in ('scripts/gpu_material_laws.py','src/physics/CohesiveInterfaceKernel.hpp','src/material/ConnectorModeKernel.hpp','client/voxel-lab/material-laws.json','src/material/MaterialCatalog.cpp','src/material/ConnectorPlasticity.cpp','src/physics/CohesiveInterface.cpp','scripts/gpu_material_frames.py','src/physics/FiniteFrameKernel.hpp','src/physics/MaterialWrench.cpp','src/physics/RotationStrain.cpp'):
    h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes())
   material_hash=h.hexdigest()
  cpu_hash=None;cpu_source=None;cpu_binary=None
  if self.cpu_library:
   from cpu_coupled_world import disk_source_hash,implementation_hash
   cpu_source=disk_source_hash();cpu_hash=implementation_hash();cpu_binary=hashlib.sha256(self.cpu_library.read_bytes()).hexdigest()
  image_verified=bool(receipt and receipt.get('schema')=='banjo.cpu-image-identity.v1' and receipt.get('cpu_source_sha256')==cpu_source and receipt.get('cpu_implementation_sha256')==cpu_hash and receipt.get('native_sha256')==actual)
  source_verified=image_verified if receipt else bool(cpu_source and checkpoint.get('cpu_coupled_source_sha256')==cpu_source)
  return {'field_references':{key:{'available':path is not None,'binary_sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path else None} for key,path in self.field_libraries.items()},'cpu_coupled_available':self.cpu_library is not None,'coupled_backend':'cpu-implicit-body' if self.cpu_library else 'cupy-implicit-body',
   'cpu_coupled_source_sha256':cpu_source,'cpu_coupled_implementation_sha256':cpu_hash,'cpu_coupled_binary_sha256':cpu_binary,
   'cpu_image_identity_verified':image_verified,'cpu_coupled_source_verified':source_verified,'checkpoint':checkpoint,'native_sha256':actual,'native_verified':bool(checkpoint.get('native_sha256')==actual),'website_revision':revision,'local_changes':dirty,'server_revision':self.started_revision,'restart_pending':revision!=self.started_revision,'gpu_available':self.gpu_python is not None,'gpu_source_sha256':gpu_hash,'gpu_worker_sha256':worker_hash,'physx_source_sha256':physx_hash,'physx_source_verified':bool(physx_hash and checkpoint.get('physx_source_sha256')==physx_hash),'gpu_source_verified':bool(gpu_hash and checkpoint.get('gpu_source_sha256')==gpu_hash and checkpoint.get('gpu_worker_sha256')==worker_hash),'gpu_material_source_sha256':material_hash,'gpu_material_source_verified':bool(material_hash and checkpoint.get('gpu_material_source_sha256')==material_hash),'gpu_coupled_source_sha256':coupled_hash,'gpu_coupled_source_verified':bool(coupled_hash and checkpoint.get('gpu_coupled_source_sha256')==coupled_hash)}
 def session(self,key,backend=None):
  if type(key) is not str or not key:raise ValueError('Invalid session identifier')
  with self.lock:
   for old,s in list(self.sessions.items()):
    if time.monotonic()-s.last>600:s.close();del self.sessions[old]
   if key not in self.sessions:raise SessionExpired('Session expired; reset the scene')
   if backend and self.sessions[key].backend!=backend:raise ValueError('Session belongs to a different physics backend')
   return self.sessions[key]
class Handler(BaseHTTPRequestHandler):
 def send(self,status,body,kind='application/json'):
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
 def host_allowed(self):
  host=urlsplit('//'+self.headers.get('Host','')).hostname
  return host in access_gate.LOOPBACK or bool(self.server.app.public_host and host==self.server.app.public_host)
 def origin_allowed(self):
  origin=self.headers.get('Origin')
  return origin is None or origin in ('http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host',''))
 def do_GET(self):
  if not self.host_allowed():self.send(403,b'{"error":"Host refused"}');return
  if access_gate.answered(self,'GET'):return
  path=self.path.split('?')[0]
  if path=='/world' or (path=='/' and self.server.cpu_library):
   self.send_response(303);self.send_header('Location','/machine');self.end_headers();return
  if path=='/api/checkpoint':
   try:self.send(200,json.dumps(self.server.checkpoint_status()).encode())
   except OSError:self.send(503,b'{"error":"Running native build cannot be inspected"}')
   return
  if path in ['/world.html','/sheets.html','/drop.html','/tests.html','/status.html','/index.html']:
   self.send_response(303);self.send_header('Location','/');self.send_header('Cache-Control','no-store');self.end_headers();return
  if path.startswith('/api/log/'):
   try:
    s=self.server.session(path.removeprefix('/api/log/'))
   except ValueError as e:self.send(404,json.dumps({'error':str(e)}).encode());return
   self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close');self.end_headers()
   try:
    for row in s.iter_log():self.wfile.write(row)
   except (BrokenPipeError,ConnectionResetError):pass
   return
  if path not in ASSETS:self.send(404,b'{}');return
  kind={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','mjs':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','json':'application/json'}[ASSETS[path].rsplit('.',1)[1]]
  self.send(200,(ROOT/ASSETS[path]).read_bytes(),kind)
 def do_POST(self):
  try:
   # Consume the bounded body before any refusal. Closing a socket with an
   # unread POST can reset the client connection instead of delivering 401/400.
   length=int(self.headers.get('Content-Length','0'))
   if not 0<=length<=2_010_000:raise ValueError('Request size invalid')
   self.connection.settimeout(30.)
   body=self.rfile.read(length)
   if not self.host_allowed() or not self.origin_allowed():raise ValueError('Host or cross-origin request refused')
   if self.path=='/login':
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=4096:raise ValueError('Login request size invalid')
    if access_gate.answered(self,'POST',body):return
   elif access_gate.answered(self,'POST'):return
   if self.path=='/api/machine':self.machine(body);return
   if self.path=='/api/representation':
    if not self.origin_allowed():raise ValueError('Cross-origin request refused')
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=4096:raise ValueError('Representation request size invalid')
    data=json.loads(body)
    if not isinstance(data,dict) or set(data)!={'declaration'}:raise ValueError('Invalid representation declaration')
    # This separate endpoint makes no claim to execute the GPU contact solver.
    # One bounded CPU-reference experiment; no persistent scene to mutate.
    from solid_representation import experiment
    if not self.server.representation_busy.acquire(blocking=False):raise ValueError('Representation reference is busy; retry after it finishes')
    try:r=experiment(data['declaration'])
    finally:self.server.representation_busy.release()
    self.send(200,json.dumps(r,separators=(',',':'),allow_nan=False).encode());return
   if self.path in ('/api/mechanisms/run','/api/flow-reference'):
    data=json.loads(body)
    if not isinstance(data,dict):raise ValueError('Declaration must be an object')
    kind='mechanisms' if self.path=='/api/mechanisms/run' else 'flow'
    library=self.server.field_libraries[kind]
    if library is None:raise ValueError('Native '+kind+' reference is unavailable; no substitute response')
    if not self.server.field_busy.acquire(blocking=False):raise ValueError('Field reference is busy; retry after it finishes')
    try:
     if kind=='mechanisms':
      if length>4096:raise ValueError('Mechanism declaration size invalid')
      from mechanisms import run_experiment
      r=run_experiment(data,library)
     else:
      if set(data) not in ({'declaration'},{'declaration','checkpoint'}):raise ValueError('Invalid flow declaration')
      from flowing_matter import run
      r=run(data['declaration'],library,checkpoint=data.get('checkpoint'))
    finally:self.server.field_busy.release()
    self.send(200,json.dumps(r,separators=(',',':'),allow_nan=False).encode());return
   if self.path not in ('/api/world','/api/gpu','/api/coupled','/api/thermal-fields'):raise ValueError('Unknown endpoint')
   backend='thermal-fields' if self.path=='/api/thermal-fields' else ('cpu-coupled' if self.server.cpu_library else 'gpu') if self.path=='/api/coupled' else 'gpu' if self.path=='/api/gpu' else 'cpu'
   if backend=='thermal-fields' and self.server.field_libraries[backend] is None:raise ValueError('Native thermal reference is unavailable; no substitute response')
   if backend=='gpu' and not self.server.gpu_python:raise ValueError('GPU runtime is not configured; no CPU fallback')
   if not self.origin_allowed():raise ValueError('Cross-origin request refused')
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=2_010_000:raise ValueError('Request size invalid')
   data=json.loads(body)
   if not isinstance(data,dict):raise ValueError('Command must be an object')
   op=data.get('op')
   if op!='restore' and length>4096:raise ValueError('Request size invalid')
   if op in ('create','restore'):
    if op=='create' and (set(data)!={'op','declaration'} or not isinstance(data['declaration'],dict)):raise ValueError('Invalid scene declaration')
    if op=='restore' and (backend not in ('gpu','cpu-coupled','thermal-fields') or set(data)!={'op','checkpoint'} or not isinstance(data['checkpoint'],dict)):raise ValueError('Invalid checkpoint restore')
    with self.server.lock:
     for key,s in list(self.server.sessions.items()):
      if time.monotonic()-s.last>600:s.close();del self.server.sessions[key]
     if len(self.server.sessions)>=8:raise ValueError('Eight scenes active; close or reset an old scene')
     command=[str(self.server.gpu_python),str(ROOT/'scripts/gpu-contact-worker.py')] if backend=='gpu' else None
     if backend=='cpu-coupled':command=[sys.executable,str(ROOT/'scripts/cpu-coupled-worker.py')]
     if backend=='thermal-fields':command=[sys.executable,str(ROOT/'scripts/thermal-field-worker.py')]
     s=Session(self.server.native,self.server.logs,self.server.checkpoint_status(),worker_command=command,backend=backend);key=uuid.uuid4().hex
     try:r=s.manual(data)
     except Exception:s.close();raise
     if r['ok']:self.server.sessions[key]=s
     else:s.close()
    r['session']=key
   elif op in ['play','frame']:
    if backend=='thermal-fields':raise ValueError('Thermal fields use bounded manual advance; scheduler is not qualified')
    allowed={'op','session','running','target_time_s'} if op=='play' else {'op','session','after','wait_ms'}
    if set(data)!=allowed:raise ValueError('Invalid pipeline command fields')
    s=self.server.session(data['session'],backend)
    if op=='play':
     if type(data['running']) is not bool:raise ValueError('Running must be boolean')
     r=s.play(data['running'],data['target_time_s'])
    else:
     if type(data['after']) is not int or not 0<=data['after']<=1_000_000:raise ValueError('Invalid frame sequence')
     if type(data['wait_ms']) is not int or not 0<=data['wait_ms']<=250:raise ValueError('Frame wait must be 0–250 ms')
     r=s.frame(data['after'],data['wait_ms'])
    r['session']=data['session']
   elif op in ['advance','snapshot','close','accelerate_object','strain','unload','export','inspect_modes']:
    allowed={'op','session','steps'} if op=='advance' else {'op','session','object','acceleration_m_s2'} if op=='accelerate_object' else {'op','session','opening_m'} if op=='strain' else {'op','session'}
    if set(data)!=allowed:raise ValueError('Invalid command fields')
    try:s=self.server.session(data['session'],backend)
    except SessionExpired:
     if op!='close':raise
     s=None
    if backend in ('gpu','cpu-coupled','thermal-fields') and op=='accelerate_object':raise ValueError('Actuation is not implemented for this reference')
    if op=='inspect_modes' and backend!='cpu-coupled':raise ValueError('Mode preparation requires the explicit native CPU reference')
    if op=='export' and backend!='thermal-fields' and (backend not in ('gpu','cpu-coupled') or not s.current['state'].get('objects')):raise ValueError('Object checkpoint export requires the coupled lab')
    if op in ('strain','unload') and (backend!='gpu' or not s.current['state'].get('controlled_loading')):raise ValueError('Material loading requires the controlled GPU inspector')
    if op=='close':
     with self.server.lock:
      if s:s.close();self.server.sessions.pop(data['session'],None)
     r={'ok':True,'already_closed':s is None}
    else:
     maximum=200 if backend=='thermal-fields' else 16
     if op=='advance' and (type(data['steps']) is not int or not 1<=data['steps']<=maximum):raise ValueError('Steps must be 1–'+str(maximum))
     r=s.manual({k:v for k,v in data.items() if k!='session'}) if op in ['advance','accelerate_object','strain','unload','export','inspect_modes'] else s.frame(0,0);r['session']=data['session']
   else:raise ValueError('Unknown operation')
   self.send(200,json.dumps(r,separators=(',',':')).encode())
  except SessionExpired as e:self.send(410,json.dumps({'ok':False,'error':str(e),'code':'session_expired'}).encode())
  except RuntimeError as e:self.send(422,json.dumps({'ok':False,'error':str(e),'code':'physics_refused'}).encode())
  except (ValueError,TypeError,KeyError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def machine(self,body):
  # One live machine world per session; every response is the engine's own
  # measured state. A refused declaration answers with its problems in words.
  from machine_world import MachineRefused
  import machine_chat, machine_game
  host=self.server.machines
  try:
   if len(body)>65536:raise ValueError('Machine request size invalid')
   data=json.loads(body)
   if not isinstance(data,dict):raise ValueError('Command must be an object')
   op=data.get('op')
   if op=='open':r=host.open(data.get('spec'))
   elif op=='check':
    from machine_world import compile_spec
    c=compile_spec(data.get('spec'));r={'ok':True,'parts':len(c['parts']),'cells':c['cells'],'notes':c['notes']}
   elif op=='play':r=host.get(data.get('session')).play(bool(data.get('running')),data.get('speed'))
   elif op=='frame':
    after,wait=data.get('after',0),data.get('wait_ms',0)
    if type(after) is not int or not 0<=after<=10**9 or type(wait) is not int or not 0<=wait<=250:raise ValueError('Invalid frame request')
    r=host.get(data.get('session')).frame(after,wait)
   elif op=='close':r=host.close(data.get('session'))
   elif op=='chat':
    if not self.server.chat_busy.acquire(blocking=False):raise ValueError('Two chat requests are already being worked on; try again shortly')
    try:
     if data.get('level'):
      # A puzzle: the chat hints, or places pieces from the tray -- nothing else.
      r=machine_chat.respond_level(data.get('message'),machine_game.level_by_id(data.get('level')),data.get('placements') or [],
       mode=data.get('mode','hint'),last_run=data.get('last_run'),rehearse=host.rehearse)
     else:r=machine_chat.respond(data.get('message'),data.get('spec'),data.get('history'),rehearse=host.rehearse if data.get('rehearse',True) else None)
    finally:self.server.chat_busy.release()
   elif op=='levels':r={'ok':True,'levels':[machine_game.public(l) for l in machine_game.load_levels()]}
   elif op=='level_open':
    # The level's machine with the player's pieces in it, built in the engine.
    level=machine_game.level_by_id(data.get('level'))
    spec,checked,cost=machine_game.compose(level,data.get('placements') or [])
    r=host.open(spec);r['level']=machine_game.public(level);r['placements']=checked;r['cost']=cost
    host.get(r['session']).game={'level':level['id'],'checked':checked,'cost':cost,'helped':bool(data.get('helped'))}
   elif op=='level_score':
    # Stars from what the engine measured in this session's run.
    s=host.get(data.get('session'));game=getattr(s,'game',None)
    if not game:raise ValueError('That session is not a level')
    level=machine_game.level_by_id(game['level'])
    rows=(s.readouts or {}).get('stations') or [{}]
    r={'ok':True,**machine_game.stars(level,game['checked'],game['cost'],rows[0].get('at_s') if rows[0].get('done') else None,game['helped'])}
   elif op=='trial':
    if not self.server.chat_busy.acquire(blocking=False):raise ValueError('The engine is busy with another trial; try again shortly')
    try:r={'ok':True,**machine_game.trial(machine_game.level_by_id(data.get('level')),data.get('placements') or [],host.exe,host.logs,runs=3)}
    finally:self.server.chat_busy.release()
   else:raise ValueError('Unknown machine operation')
   self.send(200,json.dumps(r,separators=(',',':'),allow_nan=False).encode())
  except MachineRefused as e:self.send(422,json.dumps({'ok':False,'error':'This machine cannot be built as written','problems':e.problems}).encode())
  except machine_game.LevelRefused as e:self.send(422,json.dumps({'ok':False,'error':'Those pieces do not fit this level','problems':e.problems}).encode())
  except LookupError as e:self.send(410,json.dumps({'ok':False,'error':str(e),'code':'session_expired'}).encode())
  except machine_chat.ChatUnavailable as e:self.send(503,json.dumps({'ok':False,'error':str(e)}).encode())
  except (ValueError,TypeError,KeyError,RuntimeError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def log_message(self,*args):pass
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True);p.add_argument('--gpu-python',type=Path);p.add_argument('--cpu-library',type=Path);p.add_argument('--host',default='127.0.0.1');p.add_argument('--logs',type=Path,default=ROOT/'build/voxel-world-logs');p.add_argument('--port',type=int,default=18893);a=p.parse_args()
 server=Server((a.host,a.port),a.native.resolve(strict=True),a.logs,gpu_python=a.gpu_python.resolve(strict=True) if a.gpu_python else None,cpu_library=a.cpu_library.resolve(strict=True) if a.cpu_library else None,password=os.environ.get('BANJO_PASSWORD'),public_host=os.environ.get('BANJO_PUBLIC_HOST'))
 print(f'Voxel world http://127.0.0.1:{a.port}/',flush=True)
 try:server.serve_forever()
 finally:
  for s in server.sessions.values():s.close()
  server.machines.close_all()
  server.server_close()
