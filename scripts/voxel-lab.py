"""Local, bounded native voxel world. No old website routes or simulation cache."""
import argparse, bz2, copy, gzip, hashlib, io, json, queue, struct, subprocess, threading, time, uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ASSETS={'/':'client/voxel-lab/index.html','/world.js':'client/voxel-lab/world.js','/playback.mjs':'client/voxel-lab/playback.mjs','/style.css':'client/voxel-lab/style.css','/three.module.js':'playground/vendor/three.module.js','/three.core.js':'playground/vendor/three.core.js','/gpu':'client/voxel-lab/gpu.html','/gpu.js':'client/voxel-lab/gpu.js','/gpu.css':'client/voxel-lab/gpu.css','/materials':'client/voxel-lab/materials.html','/materials.js':'client/voxel-lab/materials.js','/materials.css':'client/voxel-lab/materials.css'}
ASSETS.update({'/coupled':'client/voxel-lab/coupled.html','/coupled.js':'client/voxel-lab/coupled.js'})

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
 except (OSError,subprocess.SubprocessError):return None,None
class Session:
 def __init__(self,native,logs,checkpoint=None,worker_command=None):
  self.backend='gpu' if worker_command else 'cpu'
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
   if self.bytes+len(compressed)>32_000_000 or self.uncompressed_bytes+len(row)>256_000_000:raise ValueError('Session record limit reached; reset to continue')
   with self.path.open('ab') as f:f.write(compressed)
   self.bytes+=len(compressed);self.uncompressed_bytes+=len(row)
   self.previous_record=copy.deepcopy(data)
 def iter_log(self):
  # Snapshot at most the existing 32 MB compressed bound. Expand one exact
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
    if reply['ok'] or command.get('op')!='accelerate_object' or 'delivery_failure' in reply:
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
    reply=self.call({'op':'advance','steps':steps},record=self.backend=='gpu');cost=time.monotonic()-start
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
 def __init__(self,address,native,logs,checkpoint_path=None,gpu_python=None):
  super().__init__(address,Handler);self.native=native;self.logs=logs;logs.mkdir(parents=True,exist_ok=True);self.sessions={};self.lock=threading.Lock()
  self.checkpoint_path=checkpoint_path or ROOT/'client/voxel-lab/checkpoint.json';self.started_revision,_=repository_state()
  self.gpu_python=gpu_python
 def checkpoint_status(self):
  try:
   checkpoint=json.loads(self.checkpoint_path.read_text(encoding='utf8'))
   if not isinstance(checkpoint,dict):raise ValueError('Invalid checkpoint')
  except (ValueError,OSError):checkpoint={}
  revision,dirty=repository_state();actual=hashlib.sha256(self.native.read_bytes()).hexdigest()
  gpu_hash=hashlib.sha256((ROOT/'scripts/gpu_contact_world.py').read_bytes()).hexdigest() if self.gpu_python else None
  worker_hash=hashlib.sha256((ROOT/'scripts/gpu-contact-worker.py').read_bytes()).hexdigest() if self.gpu_python else None
  physx_hash=hashlib.sha256((ROOT/'scripts/physx_contact_world.py').read_bytes()).hexdigest() if self.gpu_python else None
  material_hash=None
  coupled_hash=None
  if self.gpu_python:
   h=hashlib.sha256()
   for name in ('scripts/gpu_coupled_world.py','src/physics/FiniteFrameKernel.hpp','src/physics/CohesiveInterfaceKernel.hpp','src/material/ConnectorModeKernel.hpp','src/physics/MaterialHistoryKernel.hpp','src/physics/NormalComplianceKernel.hpp','src/physics/CoupledGpuKernel.hpp','client/voxel-lab/material-laws.json'):
    h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes())
   coupled_hash=h.hexdigest()
   h=hashlib.sha256()
   for name in ('scripts/gpu_material_laws.py','src/physics/CohesiveInterfaceKernel.hpp','src/material/ConnectorModeKernel.hpp','client/voxel-lab/material-laws.json','src/material/MaterialCatalog.cpp','src/material/ConnectorPlasticity.cpp','src/physics/CohesiveInterface.cpp','scripts/gpu_material_frames.py','src/physics/FiniteFrameKernel.hpp','src/physics/MaterialWrench.cpp','src/physics/RotationStrain.cpp'):
    h.update(name.encode());h.update(b'\0');h.update((ROOT/name).read_bytes())
   material_hash=h.hexdigest()
  return {'checkpoint':checkpoint,'native_sha256':actual,'native_verified':bool(checkpoint.get('native_sha256')==actual),'website_revision':revision,'local_changes':dirty,'server_revision':self.started_revision,'restart_pending':revision!=self.started_revision,'gpu_available':self.gpu_python is not None,'gpu_source_sha256':gpu_hash,'gpu_worker_sha256':worker_hash,'physx_source_sha256':physx_hash,'physx_source_verified':bool(physx_hash and checkpoint.get('physx_source_sha256')==physx_hash),'gpu_source_verified':bool(gpu_hash and checkpoint.get('gpu_source_sha256')==gpu_hash and checkpoint.get('gpu_worker_sha256')==worker_hash),'gpu_material_source_sha256':material_hash,'gpu_material_source_verified':bool(material_hash and checkpoint.get('gpu_material_source_sha256')==material_hash),'gpu_coupled_source_sha256':coupled_hash,'gpu_coupled_source_verified':bool(coupled_hash and checkpoint.get('gpu_coupled_source_sha256')==coupled_hash)}
 def session(self,key,backend=None):
  with self.lock:
   for old,s in list(self.sessions.items()):
    if time.monotonic()-s.last>600:s.close();del self.sessions[old]
   if key not in self.sessions:raise ValueError('Session expired; reset the scene')
   if backend and self.sessions[key].backend!=backend:raise ValueError('Session belongs to a different physics backend')
   return self.sessions[key]
class Handler(BaseHTTPRequestHandler):
 def send(self,status,body,kind='application/json'):
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
 def do_GET(self):
  path=self.path.split('?')[0]
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
  kind={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','mjs':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[ASSETS[path].rsplit('.',1)[1]]
  self.send(200,(ROOT/ASSETS[path]).read_bytes(),kind)
 def do_POST(self):
  try:
   if self.path not in ('/api/world','/api/gpu'):raise ValueError('Unknown endpoint')
   backend='gpu' if self.path=='/api/gpu' else 'cpu'
   if backend=='gpu' and not self.server.gpu_python:raise ValueError('GPU runtime is not configured; no CPU fallback')
   if self.headers.get('Origin') not in (None,'http://'+self.headers.get('Host','')):raise ValueError('Cross-origin request refused')
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=4096:raise ValueError('Request size invalid')
   data=json.loads(self.rfile.read(length))
   if not isinstance(data,dict):raise ValueError('Command must be an object')
   op=data.get('op')
   if op=='create':
    if set(data)!={'op','declaration'} or not isinstance(data['declaration'],dict):raise ValueError('Invalid scene declaration')
    with self.server.lock:
     for key,s in list(self.server.sessions.items()):
      if time.monotonic()-s.last>600:s.close();del self.server.sessions[key]
     if len(self.server.sessions)>=8:raise ValueError('Eight scenes active; close or reset an old scene')
     command=[str(self.server.gpu_python),str(ROOT/'scripts/gpu-contact-worker.py')] if backend=='gpu' else None
     s=Session(self.server.native,self.server.logs,self.server.checkpoint_status(),worker_command=command);key=uuid.uuid4().hex
     try:r=s.manual(data)
     except Exception:s.close();raise
     if r['ok']:self.server.sessions[key]=s
     else:s.close()
    r['session']=key
   elif op in ['play','frame']:
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
   elif op in ['advance','snapshot','close','accelerate_object','strain','unload']:
    allowed={'op','session','steps'} if op=='advance' else {'op','session','object','acceleration_m_s2'} if op=='accelerate_object' else {'op','session','opening_m'} if op=='strain' else {'op','session'}
    if set(data)!=allowed:raise ValueError('Invalid command fields')
    s=self.server.session(data['session'],backend)
    if backend=='gpu' and op=='accelerate_object':raise ValueError('GPU actuation is not implemented')
    if op in ('strain','unload') and (backend!='gpu' or not s.current['state'].get('controlled_loading')):raise ValueError('Material loading requires the controlled GPU inspector')
    if op=='close':
     with self.server.lock:s.close();self.server.sessions.pop(data['session'],None)
     r={'ok':True}
    else:
     if op=='advance' and (type(data['steps']) is not int or not 1<=data['steps']<=16):raise ValueError('Steps must be 1–16')
     r=s.manual({k:v for k,v in data.items() if k!='session'}) if op in ['advance','accelerate_object','strain','unload'] else s.frame(0,0);r['session']=data['session']
   else:raise ValueError('Unknown operation')
   self.send(200,json.dumps(r,separators=(',',':')).encode())
  except (ValueError,TypeError,KeyError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def log_message(self,*args):pass
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True);p.add_argument('--gpu-python',type=Path);p.add_argument('--port',type=int,default=18893);a=p.parse_args()
 server=Server(('127.0.0.1',a.port),a.native.resolve(strict=True),ROOT/'build/voxel-world-logs',gpu_python=a.gpu_python.resolve(strict=True) if a.gpu_python else None)
 print(f'Voxel world http://127.0.0.1:{a.port}/',flush=True)
 try:server.serve_forever()
 finally:
  for s in server.sessions.values():s.close()
  server.server_close()
