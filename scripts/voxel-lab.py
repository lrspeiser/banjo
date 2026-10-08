"""Local, bounded native voxel world. No old website routes or simulation cache."""
import argparse, gzip, hashlib, json, queue, subprocess, threading, time, uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ASSETS={'/':'client/voxel-lab/index.html','/world.js':'client/voxel-lab/world.js','/playback.mjs':'client/voxel-lab/playback.mjs','/style.css':'client/voxel-lab/style.css','/three.module.js':'playground/vendor/three.module.js','/three.core.js':'playground/vendor/three.core.js'}
def repository_state():
 try:
  revision=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True,timeout=3).strip()
  dirty=bool(subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain'],text=True,timeout=3).strip())
  return revision,dirty
 except (OSError,subprocess.SubprocessError):return None,None
class Session:
 def __init__(self,native,logs,checkpoint=None):
  self.proc=subprocess.Popen([str(native),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
  self.output=queue.Queue(maxsize=2);self.lock=threading.Lock();self.record_lock=threading.Lock();self.last=time.monotonic();self.path=logs/(uuid.uuid4().hex+'.jsonl.gz');self.bytes=0;self.uncompressed_bytes=0
  self.condition=threading.Condition();self.closed=False;self.playing=False;self.calculating=False;self.latest=None;self.current=None;self.frame_id=0
  self.target_ticks=0;self.started=0.;self.started_time=0.;self.elapsed_s=0.;self.batch_cost_s=.001;self.max_batch_s=0.;self.pending_commands=[];self.last_publish=0.
  self.batch_samples=deque(maxlen=256);self.current_at=0.;self.latest_at=0.
  def reader():
   for line in self.proc.stdout:self.output.put(line)
   self.output.put(None)
  threading.Thread(target=reader,daemon=True).start()
  self.write({'native_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),'assets':{k:hashlib.sha256((ROOT/v).read_bytes()).hexdigest() for k,v in ASSETS.items()},'checkpoint':checkpoint})
  threading.Thread(target=self.simulate,daemon=True).start()
 def write(self,data):
  row=(json.dumps(data,separators=(',',':'))+'\n').encode('utf8');compressed=gzip.compress(row,compresslevel=1,mtime=0)
  with self.record_lock:
   if self.bytes+len(compressed)>32_000_000 or self.uncompressed_bytes+len(row)>256_000_000:raise ValueError('Session record limit reached; reset to continue')
   with self.path.open('ab') as f:f.write(compressed)
   self.bytes+=len(compressed);self.uncompressed_bytes+=len(row)
 def read_log(self):
  with self.record_lock:data=self.path.read_bytes()
  return gzip.decompress(data)
 def call(self,command,record=True):
  with self.lock:
   self.last=time.monotonic();self.proc.stdin.write(json.dumps(command)+'\n');self.proc.stdin.flush()
   try:line=self.output.get(timeout=25)
   except queue.Empty:self.close();raise ValueError('Native calculation exceeded 25 seconds; session stopped')
   if line is None:raise ValueError('Native process stopped')
   reply=json.loads(line)
   if record:self.write({'request':command,'response':reply})
   return reply
 def metrics(self):
  now=time.monotonic();elapsed=max(0.,now-self.started) if self.started and (self.playing or self.calculating) else self.elapsed_s
  physical=max(0.,self.current['state']['time_s']-self.started_time) if self.current and self.started else 0.
  ordered=sorted(self.batch_samples);p95=ordered[max(0,(95*len(ordered)+99)//100-1)] if ordered else 0.
  return {'running':self.playing,'calculating':self.calculating,'realtime_ratio':physical/elapsed if elapsed else 0.,'wall_s':elapsed,
          'max_native_batch_ms':self.max_batch_s*1000,'native_batch_budget_ms':8,'frame_hz_target':30,'buffered_frames':1,
          'native_batch_p95_ms':p95*1000,'batch_sample_count':len(ordered),'batch_sample_limit':256,
          'published_state_age_ms':max(0.,now-self.latest_at)*1000 if self.latest_at else 0.,
          'current_state_age_ms':max(0.,now-self.current_at)*1000 if self.current_at else 0.,
          'journal_compressed_bytes':self.bytes,'journal_uncompressed_bytes':self.uncompressed_bytes,
          'physics_changed':False,'status':'running' if self.playing else 'pausing' if self.calculating else 'paused'}
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
   with self.condition:self.current_at=time.monotonic();self.publish(reply)
   return reply
  finally:
   with self.condition:self.calculating=False;self.condition.notify_all()
 def play(self,running,target):
  with self.condition:
   if self.closed or not self.latest:raise ValueError('Session unavailable')
   if running:
    if self.calculating and not self.playing:raise ValueError('Current native batch is still finishing')
    if not self.latest['ok']:raise ValueError('Native gate refused; reset to continue')
    state=self.current['state'];dt=state['dt_s']
    if type(target) not in (int,float) or not 0<target<=2:raise ValueError('Target time must be within two physical seconds')
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
   if not reply['ok']:reply['error']=self.latest['error']
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
    steps=min(16,max(1,int(.008/max(.0001,self.batch_cost_s))),self.target_ticks-state['ticks'])
    if steps<=0:self.playing=False;self.condition.notify_all();continue
    self.calculating=True
   start=time.monotonic()
   try:
    reply=self.call({'op':'advance','steps':steps},record=False);cost=time.monotonic()-start
    with self.condition:
     self.calculating=False;self.current=reply;self.elapsed_s=max(0.,time.monotonic()-self.started);self.batch_cost_s=.5*self.batch_cost_s+.5*cost/steps;self.max_batch_s=max(self.max_batch_s,cost)
     self.current_at=time.monotonic();self.batch_samples.append(cost)
     self.pending_commands.append(steps)
     if not reply['ok'] or reply['state']['ticks']>=self.target_ticks:self.playing=False
     # Keep only the latest frame in memory. Publish at most 30 Hz plus an
     # immediate final/pause/failure frame; no accumulating playback queue.
     if not self.playing or time.monotonic()-self.last_publish>=1/30:self.publish(reply,record=True)
     self.condition.notify_all()
   except (ValueError,OSError,TypeError,KeyError) as error:
    with self.condition:
     self.calculating=False;self.playing=False
     self.publish(dict(self.current,ok=False,error=str(error)));self.condition.notify_all()
 def close(self):
  with self.condition:self.closed=True;self.playing=False;self.condition.notify_all()
  if self.proc.poll() is None:self.proc.terminate()
class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,native,logs,checkpoint_path=None):
  super().__init__(address,Handler);self.native=native;self.logs=logs;logs.mkdir(parents=True,exist_ok=True);self.sessions={};self.lock=threading.Lock()
  self.checkpoint_path=checkpoint_path or ROOT/'client/voxel-lab/checkpoint.json';self.started_revision,_=repository_state()
 def checkpoint_status(self):
  try:
   checkpoint=json.loads(self.checkpoint_path.read_text(encoding='utf8'))
   if not isinstance(checkpoint,dict):raise ValueError('Invalid checkpoint')
  except (ValueError,OSError):checkpoint={}
  revision,dirty=repository_state();actual=hashlib.sha256(self.native.read_bytes()).hexdigest()
  return {'checkpoint':checkpoint,'native_sha256':actual,'native_verified':bool(checkpoint.get('native_sha256')==actual),'website_revision':revision,'local_changes':dirty,'server_revision':self.started_revision,'restart_pending':revision!=self.started_revision}
 def session(self,key):
  with self.lock:
   for old,s in list(self.sessions.items()):
    if time.monotonic()-s.last>600:s.close();del self.sessions[old]
   if key not in self.sessions:raise ValueError('Session expired; reset the scene')
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
   try:s=self.server.session(path.removeprefix('/api/log/'));self.send(200,s.read_log(),'application/x-ndjson');return
   except ValueError as e:self.send(404,json.dumps({'error':str(e)}).encode());return
  if path not in ASSETS:self.send(404,b'{}');return
  kind={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','mjs':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[ASSETS[path].rsplit('.',1)[1]]
  self.send(200,(ROOT/ASSETS[path]).read_bytes(),kind)
 def do_POST(self):
  try:
   if self.path!='/api/world':raise ValueError('Unknown endpoint')
   if self.headers.get('Origin') not in (None,'http://'+self.headers.get('Host','')):raise ValueError('Cross-origin request refused')
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=4096:raise ValueError('Request size invalid')
   data=json.loads(self.rfile.read(length));op=data.get('op')
   if op=='create':
    if set(data)!={'op','declaration'} or not isinstance(data['declaration'],dict):raise ValueError('Invalid scene declaration')
    with self.server.lock:
     for key,s in list(self.server.sessions.items()):
      if time.monotonic()-s.last>600:s.close();del self.server.sessions[key]
     if len(self.server.sessions)>=8:raise ValueError('Eight scenes active; close or reset an old scene')
     s=Session(self.server.native,self.server.logs,self.server.checkpoint_status());key=uuid.uuid4().hex
     try:r=s.manual(data)
     except Exception:s.close();raise
     if r['ok']:self.server.sessions[key]=s
     else:s.close()
    r['session']=key
   elif op in ['play','frame']:
    allowed={'op','session','running','target_time_s'} if op=='play' else {'op','session','after','wait_ms'}
    if set(data)!=allowed:raise ValueError('Invalid pipeline command fields')
    s=self.server.session(data['session'])
    if op=='play':
     if type(data['running']) is not bool:raise ValueError('Running must be boolean')
     r=s.play(data['running'],data['target_time_s'])
    else:
     if type(data['after']) is not int or not 0<=data['after']<=1_000_000:raise ValueError('Invalid frame sequence')
     if type(data['wait_ms']) is not int or not 0<=data['wait_ms']<=250:raise ValueError('Frame wait must be 0–250 ms')
     r=s.frame(data['after'],data['wait_ms'])
    r['session']=data['session']
   elif op in ['advance','snapshot','close']:
    allowed={'op','session','steps'} if op=='advance' else {'op','session'}
    if set(data)!=allowed:raise ValueError('Invalid command fields')
    s=self.server.session(data['session'])
    if op=='close':
     with self.server.lock:s.close();self.server.sessions.pop(data['session'],None)
     r={'ok':True}
    else:
     if op=='advance' and (type(data['steps']) is not int or not 1<=data['steps']<=16):raise ValueError('Steps must be 1–16')
     r=s.manual({k:v for k,v in data.items() if k!='session'}) if op=='advance' else s.frame(0,0);r['session']=data['session']
   else:raise ValueError('Unknown operation')
   self.send(200,json.dumps(r,separators=(',',':')).encode())
  except (ValueError,TypeError,KeyError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def log_message(self,*args):pass
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--native',type=Path,required=True);p.add_argument('--port',type=int,default=18893);a=p.parse_args()
 server=Server(('127.0.0.1',a.port),a.native.resolve(strict=True),ROOT/'build/voxel-world-logs')
 print(f'Voxel world http://127.0.0.1:{a.port}/',flush=True)
 try:server.serve_forever()
 finally:
  for s in server.sessions.values():s.close()
  server.server_close()
