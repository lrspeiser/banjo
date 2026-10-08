"""Local, bounded native voxel world. No old website routes or simulation cache."""
import argparse, hashlib, json, queue, subprocess, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ASSETS={'/':'client/voxel-lab/index.html','/world.js':'client/voxel-lab/world.js','/style.css':'client/voxel-lab/style.css','/three.module.js':'playground/vendor/three.module.js','/three.core.js':'playground/vendor/three.core.js'}
class Session:
 def __init__(self,native,logs):
  self.proc=subprocess.Popen([str(native),'--serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
  self.output=queue.Queue();self.lock=threading.Lock();self.last=time.monotonic();self.path=logs/(uuid.uuid4().hex+'.jsonl');self.bytes=0
  def reader():
   for line in self.proc.stdout:self.output.put(line)
   self.output.put(None)
  threading.Thread(target=reader,daemon=True).start()
  self.write({'native_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),'assets':{k:hashlib.sha256((ROOT/v).read_bytes()).hexdigest() for k,v in ASSETS.items()}})
 def write(self,data):
  row=json.dumps(data,separators=(',',':'))+'\n';self.bytes+=len(row)
  if self.bytes>32_000_000:raise ValueError('Session record limit reached; reset to continue')
  with self.path.open('a',encoding='utf8') as f:f.write(row)
 def call(self,command):
  with self.lock:
   self.last=time.monotonic();self.proc.stdin.write(json.dumps(command)+'\n');self.proc.stdin.flush()
   try:line=self.output.get(timeout=25)
   except queue.Empty:self.close();raise ValueError('Native calculation exceeded 25 seconds; session stopped')
   if line is None:raise ValueError('Native process stopped')
   reply=json.loads(line);self.write({'request':command,'response':reply});return reply
 def close(self):
  if self.proc.poll() is None:self.proc.terminate()
class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,native,logs):
  super().__init__(address,Handler);self.native=native;self.logs=logs;logs.mkdir(parents=True,exist_ok=True);self.sessions={};self.lock=threading.Lock()
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
  if path in ['/world.html','/sheets.html','/drop.html','/tests.html','/status.html','/index.html']:
   self.send_response(303);self.send_header('Location','/');self.send_header('Cache-Control','no-store');self.end_headers();return
  if path.startswith('/api/log/'):
   try:s=self.server.session(path.removeprefix('/api/log/'));self.send(200,s.path.read_bytes(),'application/x-ndjson');return
   except ValueError as e:self.send(404,json.dumps({'error':str(e)}).encode());return
  if path not in ASSETS:self.send(404,b'{}');return
  kind={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[ASSETS[path].rsplit('.',1)[1]]
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
     s=Session(self.server.native,self.server.logs);key=uuid.uuid4().hex
     try:r=s.call(data)
     except Exception:s.close();raise
     if r['ok']:self.server.sessions[key]=s
     else:s.close()
    r['session']=key
   elif op in ['advance','snapshot','close']:
    allowed={'op','session','steps'} if op=='advance' else {'op','session'}
    if set(data)!=allowed:raise ValueError('Invalid command fields')
    s=self.server.session(data['session'])
    if op=='close':
     with self.server.lock:s.close();self.server.sessions.pop(data['session'],None)
     r={'ok':True}
    else:
     if op=='advance' and (type(data['steps']) is not int or not 1<=data['steps']<=16):raise ValueError('Steps must be 1–16')
     r=s.call({k:v for k,v in data.items() if k!='session'});r['session']=data['session']
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
