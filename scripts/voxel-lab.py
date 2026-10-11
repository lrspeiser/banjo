"""The Rube Goldberg game's server: the levels (/play), the free build (/play?level=free)
and the machine sandbox (/machine), each a live engine world (scripts/machine_world.py),
with the chat that helps (scripts/machine_chat.py). Deployed as `--site game --public`."""
import os,re,sys
from types import SimpleNamespace
import argparse, hashlib, json, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# Its own folder, for when another program loads this file as a module.
if str(ROOT/'scripts') not in sys.path:sys.path.insert(0,str(ROOT/'scripts'))
import access_gate
from urllib.parse import urlsplit
# The pages and what they load. /play is the game; /machine is the sandbox it is built on.
ASSETS={'/play':'client/voxel-lab/machine.html','/machine':'client/voxel-lab/machine.html',
 '/machine.js':'client/voxel-lab/machine.js','/machine.css':'client/voxel-lab/machine.css',
 '/machine-view.mjs':'client/voxel-lab/machine-view.mjs','/machine-default.json':'client/voxel-lab/machine-default.json',
 '/three.module.js':'client/vendor/three.module.js','/three.core.js':'client/vendor/three.core.js'}
GAME_ROUTES=set(ASSETS)|{'/api/checkpoint'}
GAME_POSTS={'/login','/api/machine'}

def public_hostnames(*values):
 """Explicit hostnames only: the existing setting and additional aliases."""
 hosts=set()
 for value in values:
  for name in (value or '').split(','):
   name=name.strip().lower().rstrip('.')
   if not name:continue
   if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',name):
    raise ValueError('Public hosts are comma-separated hostnames, without URLs, ports or wildcards')
   hosts.add(name)
 return frozenset(hosts)

class Allowance:
 """How many of something one visitor may ask for in an hour, and everyone
 in a day: what keeps a public site's chat (which spends the model's key)
 and its engine trials from being run without end. Counted in memory, so a
 restart starts the counts again."""
 def __init__(self,per_hour,per_day,what):
  self.per_hour,self.per_day,self.what=per_hour,per_day,what;self.lock=threading.Lock();self.recent={};self.day=[]
 def take(self,who):
  now=time.time()
  with self.lock:
   self.day=[t for t in self.day if now-t<86400]
   mine=self.recent[who]=[t for t in self.recent.get(who,[]) if now-t<3600]
   if len(self.day)>=self.per_day:raise ValueError(f'The {self.what} has been used {self.per_day} times today, as much as this site allows; try again tomorrow')
   if len(mine)>=self.per_hour:raise ValueError(f'That is {self.per_hour} {self.what} requests from here in an hour, as many as this site allows; try again in {int((3600-(now-mine[0]))//60)+1} minutes')
   mine.append(now);self.day.append(now)
   if len(self.recent)>10000:self.recent={k:v for k,v in self.recent.items() if v and now-v[-1]<3600}

def repository_state():
 try:
  # Outside a checkout (the image) git says so on stderr; the receipt answers.
  revision=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True,timeout=3,stderr=subprocess.DEVNULL).strip()
  dirty=bool(subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain'],text=True,timeout=3,stderr=subprocess.DEVNULL).strip())
  return revision,dirty
 except (OSError,subprocess.SubprocessError):
  receipt=ROOT/'bin/build-receipt.json'
  try:return json.loads(receipt.read_text()).get('revision'),False
  except (OSError,ValueError):return None,None
class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,native,logs,password=None,public_host=None,site='all',public=False,public_hosts=None):
  # Public: deliberately open to anyone, with no password -- only for the
  # game (--site game), where the chat and the trials are rationed instead.
  if public and site!='game':raise ValueError('only the game (--site game) may be public with no password')
  if public:password=None
  refusal=None if public else access_gate.refusal(address[0],password)
  if refusal:raise ValueError(refusal)
  self.public=public
  self.chat_allowance=Allowance(int(os.environ.get('BANJO_CHAT_PER_HOUR','12')),int(os.environ.get('BANJO_CHAT_PER_DAY','400')),'chat') if public else None
  self.trial_allowance=Allowance(int(os.environ.get('BANJO_TRIALS_PER_HOUR','30')),int(os.environ.get('BANJO_TRIALS_PER_DAY','2000')),'reliability check') if public else None
  self.feedback_allowance=Allowance(10,500,'feedback') if public else None
  self.preview_allowance=Allowance(int(os.environ.get('BANJO_PREVIEWS_PER_HOUR','300')),int(os.environ.get('BANJO_PREVIEWS_PER_DAY','6000')),'path preview') if public else None
  self.preview_busy=threading.BoundedSemaphore(2)
  if site not in ('all','game'):raise ValueError('site is all or game')
  self.site=site
  self.app=SimpleNamespace(password=password,public_host=public_host,
   public_hosts=public_hostnames(public_host,public_hosts),sessions=set(),login_destination='/play')
  super().__init__(address,Handler);self.native=native;self.logs=logs;logs.mkdir(parents=True,exist_ok=True);self.lock=threading.Lock()
  self.started_revision,_=repository_state()
  from machine_world import MachineHost,engine_path
  self.machines=MachineHost(engine_path(native),logs/'machines');self.chat_busy=threading.BoundedSemaphore(2)
 def checkpoint_status(self):
  # What the page's header shows: the code's revision, and whether this
  # server is still running an older one.
  revision,dirty=repository_state()
  return {'website_revision':revision,'local_changes':dirty,'server_revision':self.started_revision,
          'restart_pending':revision!=self.started_revision,'engine_sha256':hashlib.sha256(self.native.read_bytes()).hexdigest()}
class Handler(BaseHTTPRequestHandler):
 def send(self,status,body,kind='application/json'):
  try:
   self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
  except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
   # Navigation can close a preview's connection while the engine finishes.
   self.close_connection=True
 def host_allowed(self):
  if len(self.headers.get_all('Host',[]))!=1:return False
  try:
   value=self.headers.get('Host','')
   if any(c.isspace() for c in value):return False
   parsed=urlsplit('//'+value)
   if parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:return False
   parsed.port # Refuse malformed ports rather than dropping the connection.
   host=(parsed.hostname or '').rstrip('.')
  except ValueError:return False
  return host in access_gate.LOOPBACK or host in self.server.app.public_hosts
 def origin_allowed(self):
  origin=self.headers.get('Origin')
  return origin is None or origin in ('http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host',''))
 def do_GET(self):
  if not self.host_allowed():self.send(403,b'{"error":"Host refused"}');return
  if access_gate.answered(self,'GET'):return
  path=self.path.split('?')[0]
  # The game is the whole site: its front door is the levels.
  if path in ('/','/index.html'):
   self.send_response(303);self.send_header('Location','/play');self.end_headers();return
  if path not in GAME_ROUTES:self.send(404,b'{}');return
  if path=='/api/checkpoint':
   try:self.send(200,json.dumps(self.server.checkpoint_status()).encode())
   except OSError:self.send(503,b'{"error":"Running native build cannot be inspected"}')
   return
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
    if not 0<length<=4096:raise ValueError('Login request size invalid')
    if access_gate.answered(self,'POST',body):return
   elif access_gate.answered(self,'POST'):return
   if self.path not in GAME_POSTS:self.send(404,b'{}');return
   if self.path=='/api/machine':self.machine(body);return
   raise ValueError('Unknown endpoint')
  except (ValueError,TypeError,KeyError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def visitor(self):
  # Who is asking, for the allowances. Behind a host's proxy (Render) the
  # visitor is the first address it forwarded; otherwise the socket's.
  forwarded=self.headers.get('X-Forwarded-For','') if self.server.public else ''
  return forwarded.split(',')[0].strip() or self.client_address[0]
 def machine(self,body):
  # One live machine world per session; every response is the engine's own
  # measured state. A refused declaration answers with its problems in words.
  from machine_world import MachineRefused,SiteBusy
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
    declaration=machine_game.compose(machine_game.requested_level(data),data.get('placements') or [])[0] if data.get('level') else data.get('spec')
    c=compile_spec(declaration);r={'ok':True,'parts':len(c['parts']),'cells':c['cells'],'notes':c['notes']}
   elif op=='play':r=host.get(data.get('session')).play(bool(data.get('running')),data.get('speed'))
   elif op=='pull':r={'ok':True,**host.get(data.get('session')).pull(data.get('body'),data.get('at'),data.get('force'))}
   elif op=='frame':
    after,wait=data.get('after',0),data.get('wait_ms',0)
    if type(after) is not int or not 0<=after<=10**9 or type(wait) is not int or not 0<=wait<=250:raise ValueError('Invalid frame request')
    r=host.get(data.get('session')).frame(after,wait)
   elif op=='close':r=host.close(data.get('session'))
   elif op=='chat':
    if self.server.chat_allowance:self.server.chat_allowance.take(self.visitor())
    if not self.server.chat_busy.acquire(blocking=False):raise ValueError('Two chat requests are already being worked on; try again shortly')
    try:
     if data.get('level')=='free':
      # The free build: the chat builds what it is asked, joined piece to piece.
      r=machine_chat.respond_free(data.get('message'),machine_game.requested_level(data),data.get('placements') or [],rehearse=host.rehearse)
     elif data.get('level'):
      # A puzzle: the chat hints, or places pieces from the tray -- nothing else.
      r=machine_chat.respond_level(data.get('message'),machine_game.level_by_id(data.get('level')),data.get('placements') or [],
       mode=data.get('mode','hint'),last_run=data.get('last_run'),rehearse=host.rehearse)
     else:r=machine_chat.respond(data.get('message'),data.get('spec'),data.get('history'),rehearse=host.rehearse if data.get('rehearse',True) else None)
    finally:self.server.chat_busy.release()
   elif op=='levels':r={'ok':True,'levels':[machine_game.public(l) for l in machine_game.load_levels()],'free':machine_game.public(machine_game.free_build()),'sandbox':machine_game.sandbox_templates(),'sandbox_base':machine_game.free_build()['machine']}
   elif op=='level_open':
    # The level's machine with the player's pieces in it, built in the engine.
    level=machine_game.requested_level(data)
    # Before the piece its goal is about is placed, the level is still shown,
    # without its goal, and the page is told what it needs.
    spec,checked,cost=machine_game.compose(level,data.get('placements') or [],leave_out_goal=True)
    needs=spec.pop('_needs',None)
    r=host.open(spec);r['level']=machine_game.public(level);r['placements']=checked;r['cost']=cost;r['energy']=machine_game.pieces_energy(r['machine'])
    if needs:r['needs']=needs
    host.get(r['session']).game={'level':level['id'],'checked':checked,'cost':cost,'helped':bool(data.get('helped'))}
   elif op=='feedback':
    # A player's word about the game: one line to the log, where the host
    # keeps it (FEEDBACK ...), and to feedback.jsonl beside the machines'
    # logs. Rationed like the chat; nothing that names the player is kept.
    if self.server.feedback_allowance:self.server.feedback_allowance.take(self.visitor())
    text=data.get('text')
    if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('Feedback is 1 to 2000 characters')
    note={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'text':text.strip(),'level':str(data.get('level') or '')[:40],
     'placements':data.get('placements') if isinstance(data.get('placements'),list) else None,'last_run':data.get('last_run'),
     'screen':data.get('screen'),'touch':bool(data.get('touch')),'site':os.environ.get('RENDER_GIT_COMMIT','')[:12]}
    line=json.dumps(note,separators=(',',':'))[:16000]
    print('FEEDBACK '+line,flush=True)
    with self.server.lock:
     with open(self.server.logs/'feedback.jsonl','a',encoding='utf-8') as f:f.write(line+'\n')
    r={'ok':True}
   elif op=='level_preview':
    # Where things will go: the level rehearsed once by the engine, unpaced,
    # with its loose bodies' paths and hits. That is engine time, so it is
    # rationed and two at a time; a busy server says so (503) and the page
    # asks again a moment later.
    if self.server.preview_allowance:self.server.preview_allowance.take(self.visitor())
    if not self.server.preview_busy.acquire(blocking=False):raise SiteBusy('The engine is working out other previews; trying again in a moment')
    try:r={'ok':True,**machine_game.preview(machine_game.requested_level(data),data.get('placements') or [],host.exe,host.logs)}
    finally:self.server.preview_busy.release()
   elif op=='level_ghost':
    # A piece before it is set down: what it would be and where, and why it
    # could not go there. Compiled only, never run, so it is not rationed.
    r={'ok':True,**machine_game.ghost(machine_game.requested_level(data),data.get('placements'),data.get('index'),snapping=bool(data.get('snap')),edit_key=data.get('edit_key'))}
   elif op=='level_score':
    # Stars from what the engine measured in this session's run.
    s=host.get(data.get('session'));game=getattr(s,'game',None)
    if not game:raise ValueError('That session is not a level')
    level=machine_game.level_by_id(game['level'])
    rows=(s.readouts or {}).get('stations') or [{}]
    # And what the win took: making the pieces, and what the run put in so far.
    energy=machine_game.energy_of(s.compiled,s.readouts,s.t)
    r={'ok':True,**machine_game.stars(level,game['checked'],game['cost'],rows[0].get('at_s') if rows[0].get('done') else None,game['helped'],energy_j=energy['j']),'energy':energy}
    # A run someone pulled by hand is a test of the parts, not the machine
    # doing it: it earns nothing.
    if (s.readouts or {}).get('pulls'):r.update(tested=True,stars=0)
   elif op=='trial':
    if self.server.trial_allowance:self.server.trial_allowance.take(self.visitor())
    if not self.server.chat_busy.acquire(blocking=False):raise ValueError('The engine is busy with another trial; try again shortly')
    try:r={'ok':True,**machine_game.trial(machine_game.level_by_id(data.get('level')),data.get('placements') or [],host.exe,host.logs,runs=3)}
    finally:self.server.chat_busy.release()
   else:raise ValueError('Unknown machine operation')
   self.send(200,json.dumps(r,separators=(',',':'),allow_nan=False).encode())
  except MachineRefused as e:self.send(422,json.dumps({'ok':False,'error':'This machine cannot be built as written','problems':e.problems}).encode())
  except machine_game.LevelRefused as e:self.send(422,json.dumps({'ok':False,'error':'Those pieces do not fit this level','problems':e.problems}).encode())
  except LookupError as e:self.send(410,json.dumps({'ok':False,'error':str(e),'code':'session_expired'}).encode())
  except machine_chat.ChatUnavailable as e:self.send(503,json.dumps({'ok':False,'error':str(e)}).encode())
  except SiteBusy as e:self.send(503,json.dumps({'ok':False,'error':str(e),'code':'site_busy'}).encode())
  except (ValueError,TypeError,KeyError,RuntimeError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def log_message(self,*args):pass
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--native',type=Path,required=True,help='the engine, banjo_live_world_run (or a file beside it)')
 p.add_argument('--host',default='127.0.0.1');p.add_argument('--logs',type=Path,default=ROOT/'build/machine-logs');p.add_argument('--port',type=int,default=18893)
 p.add_argument('--site',choices=['all','game'],default='all',help='game: as deployed')
 p.add_argument('--public',action='store_true',help='the game open to anyone with no password (needs --site game); its chat and trials are rationed')
 a=p.parse_args()
 server=Server((a.host,a.port),a.native.resolve(strict=True),a.logs,password=os.environ.get('BANJO_PASSWORD'),public_host=os.environ.get('BANJO_PUBLIC_HOST'),public_hosts=os.environ.get('BANJO_PUBLIC_HOSTS'),site=a.site,public=a.public)
 print(f'Banjo http://127.0.0.1:{a.port}/play',flush=True)
 try:server.serve_forever()
 finally:
  server.machines.close_all()
  server.server_close()
