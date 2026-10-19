"""The Rube Goldberg game's server: the levels (/play), the free build (/play?level=free)
and the machine sandbox (/machine), each a live engine world (scripts/machine_world.py),
with the chat that helps (scripts/machine_chat.py). Deployed as `--site game --public`."""
import os,re,sys
from types import SimpleNamespace
import argparse, hashlib, json, sqlite3, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# Its own folder, for when another program loads this file as a module.
if str(ROOT/'scripts') not in sys.path:sys.path.insert(0,str(ROOT/'scripts'))
import access_gate
import anonymous_profiles
import community_courses
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
# The pages and what they load. /play is the game; /machine is the sandbox it is built on.
ASSETS={'/play':'client/voxel-lab/machine.html','/machine':'client/voxel-lab/machine.html','/community':'client/voxel-lab/machine.html',
 '/machine.js':'client/voxel-lab/machine.js','/machine.css':'client/voxel-lab/machine.css',
 '/machine-view.mjs':'client/voxel-lab/machine-view.mjs','/machine-default.json':'client/voxel-lab/machine-default.json',
 '/anonymous-profile.mjs':'client/voxel-lab/anonymous-profile.mjs',
 '/profile-sync.mjs':'client/voxel-lab/profile-sync.mjs',
 '/level-library.mjs':'client/voxel-lab/level-library.mjs',
 '/design-gallery.mjs':'client/voxel-lab/design-gallery.mjs',
 '/community-gallery.mjs':'client/voxel-lab/community-gallery.mjs',
 '/level-intro.mjs':'client/voxel-lab/level-intro.mjs',
 '/site-paths.mjs':'client/voxel-lab/site-paths.mjs',
 '/banjo-mark.png':'client/voxel-lab/brand/banjo-mark.png',
 '/banjo-app-icon.jpg':'client/voxel-lab/brand/banjo-app-icon.jpg',
 '/banjo-app-icon.png':'client/voxel-lab/brand/banjo-app-icon.png',
 '/banjo-favicon.png':'client/voxel-lab/brand/banjo-favicon.png',
 '/manifest.webmanifest':'client/voxel-lab/manifest.webmanifest',
 '/three.module.js':'client/vendor/three.module.js','/three.core.js':'client/vendor/three.core.js'}
GAME_ROUTES=set(ASSETS)|{'/api/checkpoint'}
GAME_POSTS={'/login','/api/machine','/api/profile','/api/community'}

def test_site_url(value):
 if not value:return None
 parsed=urlsplit(value)
 if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or
     parsed.query or parsed.fragment or any(c.isspace() for c in value)):
  raise ValueError('Test site URL must be an HTTPS URL without credentials, query or fragment')
 parsed.port
 return value.rstrip('/')

def repository_branch():
 if os.environ.get('RENDER_GIT_BRANCH'):return os.environ['RENDER_GIT_BRANCH']
 if (ROOT/'test-build.json').is_file():
  try:return json.loads((ROOT/'bin/build-receipt.json').read_text()).get('branch')
  except (OSError,ValueError):return None
 try:return subprocess.check_output(['git','-C',str(ROOT),'branch','--show-current'],text=True,timeout=3,stderr=subprocess.DEVNULL).strip() or None
 except (OSError,subprocess.SubprocessError):return None

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
 # An installed runtime is immutable even when its cache lives below a local
 # checkout. Do not let git walk up into the production/parent repository.
 if (ROOT/'test-build.json').is_file():
  try:return json.loads((ROOT/'bin/build-receipt.json').read_text()).get('revision'),False
  except (OSError,ValueError):return None,None
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
 request_queue_size=128
 daemon_threads=True
 def __init__(self,address,native,logs,password=None,public_host=None,site='all',public=False,public_hosts=None,profile_db=None,
              environment=None,profile_upstream=None,profile_namespace=None,test_url=None,base_path=None,
              test_builds=None,test_auto=None,test_source=None):
  # Public: deliberately open to anyone, with no password -- only for the
  # game (--site game), where the chat and the trials are rationed instead.
  if public and site!='game':raise ValueError('only the game (--site game) may be public with no password')
  if public:password=None
  refusal=None if public else access_gate.refusal(address[0],password)
  if refusal:raise ValueError(refusal)
  self.public=public
  self.environment=environment or os.environ.get('BANJO_ENVIRONMENT') or ('production' if public else 'local')
  if self.environment not in ('production','test','local'):raise ValueError('Environment is production, test or local')
  self.base_path=base_path if base_path is not None else os.environ.get('BANJO_BASE_PATH','')
  if self.base_path not in ('','/test') or (self.base_path and self.environment!='test'):raise ValueError('Only test builds may use /test')
  self.profile_cookie_name=anonymous_profiles.TEST_COOKIE_NAME if self.environment=='test' else anonymous_profiles.COOKIE_NAME
  if self.environment=='test':public_host=public_host or os.environ.get('RENDER_EXTERNAL_HOSTNAME')
  self.test_url=test_site_url(test_url or os.environ.get('BANJO_TEST_URL'))
  self.chat_allowance=Allowance(int(os.environ.get('BANJO_CHAT_PER_HOUR','12')),int(os.environ.get('BANJO_CHAT_PER_DAY','400')),'chat') if public else None
  self.trial_allowance=Allowance(int(os.environ.get('BANJO_TRIALS_PER_HOUR','30')),int(os.environ.get('BANJO_TRIALS_PER_DAY','2000')),'reliability check') if public else None
  self.feedback_allowance=Allowance(10,500,'feedback') if public else None
  self.preview_allowance=Allowance(int(os.environ.get('BANJO_PREVIEWS_PER_HOUR','300')),int(os.environ.get('BANJO_PREVIEWS_PER_DAY','6000')),'path preview') if public else None
  self.preview_busy=threading.BoundedSemaphore(1 if self.base_path else 2)
  from machine_world import PreviewJobs
  self.preview_jobs=PreviewJobs()
  from machine_replay import PreparedRuns
  self.prepared_runs=PreparedRuns()
  self.engine_digest=hashlib.sha256(native.read_bytes()).hexdigest() if native and native.is_file() else None
  self.optical_allowance=Allowance(3000,18000,'laser preview') if public else None
  if site not in ('all','game'):raise ValueError('site is all or game')
  self.site=site
  self.app=SimpleNamespace(password=password,public_host=public_host,
   public_hosts=public_hostnames(public_host,public_hosts),sessions=set(),login_destination='/play')
  super().__init__(address,Handler);self.native=native;self.logs=logs;logs.mkdir(parents=True,exist_ok=True);self.lock=threading.Lock()
  self.started_revision,_=repository_state()
  from machine_world import MachineHost,engine_path
  self.machines=MachineHost(engine_path(native),logs/'machines');self.chat_busy=threading.BoundedSemaphore(2)
  upstream=profile_upstream or os.environ.get('BANJO_PROFILE_UPSTREAM')
  if upstream and self.environment!='test':raise ValueError('Remote profile storage is only for the test environment')
  self.profiles=(anonymous_profiles.RemoteProfileStore(upstream,logs.parent/'profile-proxy.sqlite3',
      namespace=profile_namespace or os.environ.get('BANJO_PROFILE_NAMESPACE') or 'test') if upstream else
      anonymous_profiles.ProfileStore(profile_db or os.environ.get('BANJO_PROFILE_DB') or logs.parent/'profiles.sqlite3'))
  # The mounted test-logs directory survives source-package replacement. Test
  # courses stay separate; branch code never opens the production database.
  self.courses=community_courses.CourseStore(self.profiles.path.with_name('community.sqlite3'))
  self.course_shares=Allowance(60,1000,'shared courses')
  import bug_reports
  self.bug_reports=bug_reports.Reports(self.profiles.path.with_name('bug-reports.sqlite3'),
   os.environ.get('LINEAR_API_KEY',''),os.environ.get('BANJO_LINEAR_PROJECT_ID',bug_reports.DEFAULT_PROJECT_ID),os.environ.get('BANJO_LINEAR_TEAM_ID'))
  self.bug_reports.start()
  self.profile_creations=Allowance(20,2000,'new visitor profiles')
  self.profile_requests=Allowance(6000,100000,'profile requests')
  self.test_site=None
  if test_builds is not None or os.environ.get('BANJO_TEST_SITE')=='1':
   from test_site import TestSite
   self.test_site=TestSite(Path(test_builds or logs.parent/'test-builds'),
       f'http://127.0.0.1:{self.server_address[1]}/api/profile',
       ','.join(self.app.public_hosts),auto=test_auto if test_auto is not None else True,
       source=test_source,native=self.native)
   self.test_site.start()
 def checkpoint_status(self):
  # What the page's header shows: the code's revision, and whether this
  # server is still running an older one.
  revision,dirty=repository_state()
  return {'website_revision':revision,'local_changes':dirty,'server_revision':self.started_revision,
          'restart_pending':revision!=self.started_revision,'engine_sha256':hashlib.sha256(self.native.read_bytes()).hexdigest(),
          'bug_reporting':self.bug_reports.summary(),'environment':self.environment,'branch':repository_branch(),
          'profiles':{'shared':isinstance(self.profiles,anonymous_profiles.RemoteProfileStore),
                      'namespace':getattr(self.profiles,'namespace','production')},'test_url':'/test' if self.test_site else self.test_url,
          'base_path':self.base_path,'test_site':self.test_site.status() if self.test_site else None}
 def server_close(self):
  if getattr(self,'test_site',None):self.test_site.close()
  if hasattr(self,'bug_reports'):self.bug_reports.close()
  super().server_close()
class Handler(BaseHTTPRequestHandler):
 def route_path(self):
  path=self.path.split('?')[0]
  base=self.server.base_path
  if not base:return path
  if path==base:return '/'
  return path[len(base):] if path.startswith(base+'/') else None
 def send(self,status,body,kind='application/json',headers=None):
  try:
   csp="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'"
   if self.server.base_path or (self.server.test_site and self.path.split('?')[0].startswith('/test/')):
    host=self.headers.get('Host','');local=(urlsplit('//'+host).hostname or '') in access_gate.LOOPBACK
    prefix=('https' if self.server.public and not local or self.headers.get('X-Forwarded-Proto')=='https' else 'http')+'://'+host+'/test/'
    csp=f"default-src 'none'; script-src {prefix}; style-src {prefix}; connect-src {prefix}; img-src {prefix} blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action {prefix}"
   self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',csp)
   for key,value in (headers or {}).items():self.send_header(key,value)
   self.end_headers();self.wfile.write(body)
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
  path=self.route_path()
  if not self.server.base_path and self.server.test_site and (path=='/test' or path.startswith('/test/')):
   self.server.test_site.proxy(self,'GET');return
  if path in ('/test','/test/'):
   if self.server.test_url:self.send(303,b'',kind='text/plain',headers={'Location':self.server.test_url})
   else:self.send(503,b'{"error":"The test site has not been connected yet"}')
   return
  # The game is the whole site: its front door is the levels.
  if path in ('/','/index.html'):
   self.send(303,b'',kind='text/plain',headers={'Location':self.server.base_path+'/play'});return
  if path not in GAME_ROUTES:self.send(404,b'{}');return
  if path=='/api/checkpoint':
   try:self.send(200,json.dumps(self.server.checkpoint_status()).encode())
   except OSError:self.send(503,b'{"error":"Running native build cannot be inspected"}')
   return
  kind={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','mjs':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','json':'application/json','webmanifest':'application/manifest+json','png':'image/png','jpg':'image/jpeg'}[ASSETS[path].rsplit('.',1)[1]]
  content=(ROOT/ASSETS[path]).read_bytes()
  if path in ('/play','/machine','/community'):
   content=content.replace(b'<html lang="en">',f'<html lang="en" data-banjo-environment="{self.server.environment}" data-banjo-base="{self.server.base_path}">'.encode())
   if self.server.environment=='test':content=content.replace(b'id="environment-badge" hidden',b'id="environment-badge"')
   if self.server.base_path:
    content=content.replace(b'href="/',b'href="/test/').replace(b'src="/',b'src="/test/').replace(b'action="/',b'action="/test/')
  elif path=='/manifest.webmanifest' and self.server.base_path:
   manifest=json.loads(content);manifest.update(name='Banjo Test',short_name='Banjo Test',start_url='/test/play',scope='/test/')
   for icon in manifest.get('icons',[]):icon['src']='/test'+icon['src']
   content=json.dumps(manifest).encode()
  self.send(200,content,kind)
 def do_POST(self):
  try:
   # Consume the bounded body before any refusal. Closing a socket with an
   # unread POST can reset the client connection instead of delivering 401/400.
   length=int(self.headers.get('Content-Length','0'))
   path=self.route_path()
   limit=anonymous_profiles.MAX_REQUEST_BYTES if path in ('/api/profile','/test/api/profile') else 2_010_000
   if not 0<=length<=limit:
    self.close_connection=True;self.send(413,b'{"ok":false,"error":"Request size invalid"}');return
   self.connection.settimeout(30.)
   body=self.rfile.read(length)
   if not self.host_allowed() or not self.origin_allowed():raise ValueError('Host or cross-origin request refused')
   if not self.server.base_path and self.server.test_site and path.startswith('/test/'):
    self.server.test_site.proxy(self,'POST',body);return
   if path=='/login':
    if not 0<length<=4096:raise ValueError('Login request size invalid')
    if access_gate.answered(self,'POST',body):return
   elif access_gate.answered(self,'POST'):return
   if path not in GAME_POSTS:self.send(404,b'{}');return
   if path=='/api/machine':self.machine(body);return
   if path=='/api/profile':self.profile(body);return
   if path=='/api/community':self.community(body);return
   raise ValueError('Unknown endpoint')
  except (ValueError,TypeError,KeyError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def visitor(self):
  # Who is asking, for the allowances. Behind a host's proxy (Render) the
  # visitor is the first address it forwarded; otherwise the socket's.
  forwarded=self.headers.get('X-Forwarded-For','') if self.server.public else ''
  return forwarded.split(',')[0].strip() or self.client_address[0]
 def profile(self,body):
  try:
   def rate(allowance):
    try:allowance.take(self.visitor())
    except ValueError as error:raise anonymous_profiles.ProfileRateLimited(str(error)) from None
   rate(self.server.profile_requests)
   data=json.loads(body,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON is invalid')))
   if not isinstance(data,dict):raise ValueError('Profile request must be a JSON object')
   op=data.get('op');cookie=None
   if op=='open':
    jar=SimpleCookie()
    try:jar.load(self.headers.get('Cookie',''))
    except Exception:pass
    if self.server.profile_cookie_name in jar:
     try:cookie=anonymous_profiles.visitor_id(jar[self.server.profile_cookie_name].value)
     except anonymous_profiles.ProfileError:pass
    reply=self.server.profiles.open(data.get('visitor'),data.get('cached_visitor'),cookie,
      before_create=lambda:rate(self.server.profile_creations))
   elif op=='create':reply=self.server.profiles.create(data.get('visitor'),data.get('profile'),before_create=lambda:rate(self.server.profile_creations))
   elif op=='save':reply=self.server.profiles.save(data.get('visitor'),data.get('revision'),data.get('profile'))
   else:raise ValueError('Profile operation is open, create or save')
   reply.update(ok=True)
   if 'storage' not in reply:reply['storage']={'persistent':anonymous_profiles.storage_persistent(self.server.profiles.path)}
   headers={}
   if op=='open':
    host=(urlsplit('//'+self.headers.get('Host','')).hostname or '').rstrip('.')
    secure=(self.server.public and host not in access_gate.LOOPBACK) or self.headers.get('X-Forwarded-Proto','').split(',')[0].strip().lower()=='https'
    headers['Set-Cookie']=f'{self.server.profile_cookie_name}={reply["visitor"]}; Path={self.server.base_path+"/"}; Max-Age=31536000; SameSite=Lax; HttpOnly'+('; Secure' if secure else '')
   self.send(200,json.dumps(reply,separators=(',',':'),allow_nan=False,ensure_ascii=False).encode(),headers=headers)
  except anonymous_profiles.ProfileError as error:
   self.send(error.status,json.dumps(dict(ok=False,error=str(error),**error.data),separators=(',',':'),ensure_ascii=False).encode())
  except (ValueError,TypeError,KeyError,RecursionError,UnicodeError) as error:
   self.send(400,json.dumps({'ok':False,'error':'Invalid profile request'}).encode())
  except (OSError, sqlite3.Error):
   self.send(503,b'{"ok":false,"error":"Profile storage is unavailable; your local draft was kept"}')
 def community(self,body):
  try:
   def rate(allowance):
    try:allowance.take(self.visitor())
    except ValueError as error:raise anonymous_profiles.ProfileRateLimited(str(error)) from None
   rate(self.server.profile_requests)
   data=json.loads(body,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON')))
   if not isinstance(data,dict):raise ValueError('Invalid community request')
   op=data.get('op');store=self.server.courses
   if op=='browse':reply=store.browse(data.get('cursor'),data.get('query',''))
   elif op=='get':reply={'course':store.get(data.get('id'))}
   elif op in ('share','mine','unpublish'):
    visitor=anonymous_profiles.visitor_id(data.get('visitor'))
    saved=self.server.profiles.open(visitor);profile=saved['profile']
    if op=='share':
     if type(data.get('revision')) is not int or data['revision']!=saved['revision']:
      raise anonymous_profiles.ProfileConflict('Your save changed on another device. Reopen it before sharing.')
     rate(self.server.course_shares)
     sandbox=profile.get('sandbox')
     items=sandbox.get('items',[]) if isinstance(sandbox,dict) else []
     if not isinstance(items,list):raise anonymous_profiles.ProfileError('Save a design before sharing it.')
     design=next((row for row in items
                  if isinstance(row,dict) and row.get('id')==data.get('design_id')),None)
     if design is None:raise anonymous_profiles.ProfileMissing('Save this design before sharing it.')
     reply={'course':store.share(visitor,design,data.get('description',''),data.get('publish',False))}
    elif op=='mine':reply={'courses':store.mine(visitor)}
    else:store.unpublish(visitor,data.get('design_id'));reply={}
   else:raise ValueError('Unknown community operation')
   self.send(200,json.dumps(dict(ok=True,**reply),separators=(',',':'),ensure_ascii=False).encode())
  except anonymous_profiles.ProfileError as error:
   self.send(error.status,json.dumps(dict(ok=False,error=str(error)),ensure_ascii=False).encode())
  except (ValueError,TypeError,KeyError,RecursionError):
   self.send(400,b'{"ok":false,"error":"Invalid community request"}')
  except (OSError,sqlite3.Error):
   self.send(503,b'{"ok":false,"error":"Community storage is unavailable; your private design is safe"}')
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
   elif op=='play':
    if data.get('running'):self.server.preview_jobs.cancel(self.visitor(),data.get('preview_owner'),data.get('preview_epoch',0))
    r=host.get(data.get('session')).play(bool(data.get('running')),data.get('speed'))
   elif op=='pull':r={'ok':True,**host.get(data.get('session')).pull(data.get('body'),data.get('at'),data.get('force'))}
   elif op=='mechanical_switch_pull':r={'ok':True,**host.get(data.get('session')).mechanical_switch_pull(data.get('name'),data.get('body'),data.get('at'),data.get('force'))}
   elif op=='electrical_switch':
    if type(data.get('closed')) is not bool:raise ValueError('Switch state must be true or false')
    r={'ok':True,**host.get(data.get('session')).electrical_switch(data.get('name'),data['closed'])}
   elif op=='water_opening':
    r={'ok':True,**host.get(data.get('session')).water_opening(data.get('name'),data.get('fraction'))}
   elif op=='water_valve':
    if type(data.get('open')) is not bool:raise ValueError('Valve state must be true or false')
    r={'ok':True,**host.get(data.get('session')).water_valve(data.get('name'),data['open'])}
   elif op=='release_joint':r={'ok':True,**host.get(data.get('session')).release_joint(data.get('name'))}
   elif op=='frame':
    after,wait=data.get('after',0),data.get('wait_ms',0)
    if type(after) is not int or not 0<=after<=10**9 or type(wait) is not int or not 0<=wait<=250:raise ValueError('Invalid frame request')
    r=host.get(data.get('session')).frame(after,wait)
   elif op=='close':
    self.server.preview_jobs.cancel(self.visitor(),data.get('preview_owner'),data.get('preview_epoch',0))
    r=host.close(data.get('session'))
   elif op=='chat':
    if self.server.chat_allowance:self.server.chat_allowance.take(self.visitor())
    if not self.server.chat_busy.acquire(blocking=False):raise ValueError('Two chat requests are already being worked on; try again shortly')
    try:
     if data.get('mode')=='coach' and data.get('level'):
      r=machine_chat.respond_coach(machine_game.requested_level(data),data.get('placements') or [],
       ui=data.get('ui'),last_run=data.get('last_run'))
     elif data.get('level')=='free':
      # The free build: the chat builds what it is asked, joined piece to piece.
      r=machine_chat.respond_free(data.get('message'),machine_game.requested_level(data),data.get('placements') or [],rehearse=host.rehearse)
     elif data.get('level'):
      # A puzzle: the chat hints, or places pieces from the tray -- nothing else.
      r=machine_chat.respond_level(data.get('message'),machine_game.level_by_id(data.get('level')),data.get('placements') or [],
       mode=data.get('mode','hint'),last_run=data.get('last_run'),rehearse=host.rehearse,ui=data.get('ui'))
     else:r=machine_chat.respond(data.get('message'),data.get('spec'),data.get('history'),rehearse=host.rehearse if data.get('rehearse',True) else None)
    finally:self.server.chat_busy.release()
   elif op=='levels':r={'ok':True,'levels':[machine_game.public(l) for l in machine_game.load_levels()],'free':machine_game.public(machine_game.free_build()),'sandbox':machine_game.sandbox_templates(),'sandbox_base':machine_game.free_build()['machine'],'wall_sandbox':machine_game.sandbox_wall.world_template(machine_game.free_build()['tray']),'wall_legacy_tray':machine_game.sandbox_wall.tray()}
   elif op=='wall_into_world':
    draft=machine_game.sandbox_wall.world_draft(data.get('base',{}),data.get('placements',[]),data.get('goal'))
    machine_game.compose(machine_game.requested_level(dict(level='free',**draft)),draft['placements'])
    r=dict(ok=True,draft=draft)
   elif op=='wall_edit':
    r=dict(ok=True,**machine_game.sandbox_wall.edit_panel(data.get('base',{}),data.get('placements',[]),
        data.get('wall'),data.get('changes'),bool(data.get('add')),data.get('edit_key')))
   elif op=='easy_variant':
    if self.server.trial_allowance:self.server.trial_allowance.take(self.visitor())
    if not self.server.preview_busy.acquire(blocking=False):raise SiteBusy('The engine is testing other challenges; try again shortly')
    try:
     level=machine_game.fresh_easy(data.get('family'),data.get('seed'),host.exe,host.logs,recipe_id=data.get('recipe'))
     r={'ok':True,'level':machine_game.public(level)}
    finally:self.server.preview_busy.release()
   elif op=='level_open':
    if type(data.get('take_over',False)) is not bool:raise ValueError('Browser switch must be true or false')
    take_over=data.get('take_over',False)
    if take_over and self.server.environment!='test':raise ValueError('Switching browsers is only available on the test site')
    self.server.preview_jobs.cancel(self.visitor(),data.get('preview_owner'),data.get('preview_epoch',0))
    # The level's machine with the player's pieces in it, built in the engine.
    level=machine_game.requested_level(data)
    # Before the piece its goal is about is placed, the level is still shown,
    # without its goal, and the page is told what it needs.
    spec,checked,cost=machine_game.compose(level,data.get('placements') or [],leave_out_goal=True)
    needs=spec.pop('_needs',None)
    prepared=None
    if data.get('prepared_run'):
     from machine_world import compile_spec
     prepared=self.server.prepared_runs.take(data['prepared_run'],self.visitor(),data.get('preview_owner'),compile_spec(spec),self.server.engine_digest)
    r=host.open(spec,take_over=take_over,prepared=prepared) if prepared else host.open(spec,take_over=True) if take_over else host.open(spec)
    r['level']=machine_game.public(level);r['placements']=checked;r['cost']=cost;r['energy']=machine_game.pieces_energy(r['machine'])
    if level.get('free'):
     import sandbox_edit
     walls=machine_game.sandbox_wall.panels(level['machine']) if level.get('wall_mode',{}).get('version')==2 else []
     wall_names={p['id'] for p in walls}
     r['sandbox_objects']=[o for o in sandbox_edit.objects(level['machine']) if not any(n in wall_names or level.get('wall_mode') and n in machine_game.sandbox_wall.FOUNDATION for n in o['parts'])]
     r['sandbox_objects'] += [dict(id='wall:'+p['id'],name='Mounting wall '+str(i+1),parts=[p['id']],
        at_m=machine_game.sandbox_wall.panel_part(p)['at_m'],wall=p) for i,p in enumerate(walls)]
    if needs:r['needs']=needs
    host.get(r['session']).game={'level':level['id'],'definition':level,'checked':checked,'cost':cost,'helped':bool(data.get('helped'))}
   elif op=='feedback':
    # A player's word about the game: one line to the log, where the host
    # keeps it (FEEDBACK ...), and to feedback.jsonl beside the machines'
    # logs. Rationed like the chat; nothing that names the player is kept.
    if self.server.feedback_allowance:self.server.feedback_allowance.take(self.visitor())
    text=data.get('text')
    if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('Feedback is 1 to 2000 characters')
    note={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'text':text.strip(),'level':str(data.get('level') or '')[:40],
     'placements':data.get('placements') if isinstance(data.get('placements'),list) else None,'last_run':data.get('last_run'),
     'screen':data.get('screen'),'touch':bool(data.get('touch')),'site':self.server.started_revision,
     'base':data.get('base'),'world_t':data.get('world_t'),'replay_link':data.get('replay_link','')}
    import uuid
    delivery=self.server.bug_reports.submit(data.get('report_id') or str(uuid.uuid4()),note)
    line=json.dumps(note,separators=(',',':'),allow_nan=False)
    print('FEEDBACK '+line,flush=True)
    with self.server.lock:
     with open(self.server.logs/'feedback.jsonl','a',encoding='utf-8') as f:f.write(line+'\n')
    r={'ok':True,**delivery}
   elif op=='cancel_preparation':
    self.server.preview_jobs.cancel(self.visitor(),data.get('preview_owner'),data.get('preview_epoch',0));r={'ok':True}
   elif op=='preparation_status':
    r={'ok':True,**self.server.preview_jobs.status(self.visitor(),data.get('preview_owner'))}
   elif op=='level_preview':
    # Where things will go: the level rehearsed once by the engine, unpaced,
    # with its loose bodies' paths and hits. That is engine time, so it is
    # rationed and two at a time; a busy server says so (503) and the page
    # asks again a moment later.
    if self.server.preview_allowance:self.server.preview_allowance.take(self.visitor())
    self.server.preview_jobs.cancel(self.visitor(),data.get('preview_owner'),data.get('preview_epoch',0))
    if not self.server.preview_busy.acquire(blocking=False):raise SiteBusy('The engine is working out other previews; trying again in a moment')
    key,job=self.server.preview_jobs.begin(self.visitor(),data.get('preview_owner'),data.get('preview_epoch',0))
    try:
     r={'ok':True,**machine_game.preview(machine_game.requested_level(data),data.get('placements') or [],host.exe,host.logs,preview_job=job)}
     if not job.cancelled() and getattr(job,'replay_frames',None):
      token=self.server.prepared_runs.keep(self.visitor(),data.get('preview_owner'),job.replay_compiled,job.replay_frames,self.server.engine_digest)
      if token:r['prepared_run']=token
    finally:
     self.server.preview_jobs.end(key,job)
     self.server.preview_busy.release()
   elif op=='level_sunlight':
    if self.server.optical_allowance:self.server.optical_allowance.take(self.visitor())
    if not self.server.preview_busy.acquire(blocking=False):raise SiteBusy('The engine is measuring other previews; trying again in a moment')
    try:r={'ok':True,**machine_game.solar_preview(machine_game.requested_level(data),data.get('placements') or [],host.exe,host.logs)}
    finally:self.server.preview_busy.release()
   elif op=='level_optics':
    if self.server.optical_allowance:self.server.optical_allowance.take(self.visitor())
    if not self.server.preview_busy.acquire(blocking=False):raise SiteBusy('The engine is working out other previews; trying again in a moment')
    try:r={'ok':True,**machine_game.optical_preview(machine_game.requested_level(data),data.get('placements') or [],host.exe,host.logs)}
    finally:self.server.preview_busy.release()
   elif op=='sandbox_object':
    import sandbox_edit
    level=machine_game.requested_level(data)
    if not level.get('free'):raise ValueError('Only Sandbox apparatus can be edited')
    if level.get('wall_mode') and data.get('object') in ('part:'+n for n in machine_game.sandbox_wall.FOUNDATION):
     raise ValueError('The wall and its guard are the mounting surface. Add, move or remove the pieces mounted on it.')
    if data.get('remove'):
     base,selected,compiled=sandbox_edit.edit(level['machine'],data.get('object'),remove=True)
     before=sandbox_edit.mw.compile_spec(level['machine'])
     names=lambda c:{row['name'] for rows in [c['parts'],c['joints'],c.get('electrical',{}).get('devices',[]),c.get('electrical',{}).get('power_ports',[])] for row in rows}
     r={'ok':True,'base':base,'removed':sorted(names(before)-names(compiled))}
    else:
     r={'ok':True,**sandbox_edit.ghost(level['machine'],data.get('object'),data.get('delta'),
       snapping=bool(data.get('snap')),snap_hold=data.get('snap_hold'),nearby=bool(data.get('nearby_snap')))}
     edited=machine_game.requested_level({'level':'free','base':r['base']})
     machine_game.compose(edited,data.get('placements') or [])
   elif op=='assembly_ghost':
    level=machine_game.requested_level(data)
    r={'ok':True,**machine_game.assembly_ghost(level,data.get('placements') or [],data.get('start'))}
   elif op=='level_ghost':
    # A piece before it is set down: what it would be and where, and why it
    # could not go there. Compiled only, never run, so it is not rationed.
    level=machine_game.requested_level(data)
    if data.get('thumbnail') and level.get('free') and not level.get('wall_mode'):
     # Only the picture's construction context changes, never the saved
     # design or running world. Water apparatus needs its declared flume.
     import copy,sandbox_water_launch
     level=copy.deepcopy(level)
     level['machine']=copy.deepcopy(sandbox_water_launch.CHANNEL_BASE)
    r={'ok':True,**machine_game.ghost(level,data.get('placements'),data.get('index'),snapping=bool(data.get('snap')),edit_key=data.get('edit_key'),nearby=bool(data.get('nearby_snap')),snap_hold=data.get('snap_hold'))}
   elif op=='level_score':
    # Stars from what the engine measured in this session's run.
    s=host.get(data.get('session'));game=getattr(s,'game',None)
    if not game:raise ValueError('That session is not a level')
    level=game.get('definition') or machine_game.level_by_id(game['level'])
    rows=(s.readouts or {}).get('stations') or [{}]
    # And what the win took: making the pieces, and what the run put in so far.
    energy=machine_game.energy_of(s.compiled,s.readouts,s.t)
    r={'ok':True,**machine_game.stars(level,game['checked'],game['cost'],rows[0].get('at_s') if rows[0].get('done') else None,game['helped'],energy_j=energy['j']),'energy':energy}
    # General Pull is a test intervention. Validated manual switch handles are
    # ordinary field controls; their native pull work still enters energy.
    if s._test_pulled:r.update(tested=True,stars=0)
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
  except sqlite3.Error:self.send(503,b'{"ok":false,"error":"Bug-report storage is unavailable; keep your text and try again"}')
  except (ValueError,TypeError,KeyError,RuntimeError,OSError) as e:self.send(400,json.dumps({'ok':False,'error':str(e)}).encode())
 def log_message(self,*args):pass
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--native',type=Path,required=True,help='the engine, banjo_live_world_run (or a file beside it)')
 p.add_argument('--host',default='127.0.0.1');p.add_argument('--logs',type=Path,default=ROOT/'build/machine-logs');p.add_argument('--port',type=int,default=18893)
 p.add_argument('--site',choices=['all','game'],default='all',help='game: as deployed')
 p.add_argument('--public',action='store_true',help='the game open to anyone with no password (needs --site game); its chat and trials are rationed')
 p.add_argument('--test-source',type=Path,help='local development checkout for the co-hosted test app; disables automatic downloads')
 a=p.parse_args()
 server=Server((a.host,a.port),a.native.resolve(strict=True),a.logs,password=os.environ.get('BANJO_PASSWORD'),public_host=os.environ.get('BANJO_PUBLIC_HOST'),public_hosts=os.environ.get('BANJO_PUBLIC_HOSTS'),site=a.site,public=a.public,
    test_builds=a.logs.parent/'test-builds' if a.test_source else None,test_source=a.test_source,test_auto=False if a.test_source else None)
 print(f'Banjo http://127.0.0.1:{a.port}/play',flush=True)
 try:server.serve_forever()
 finally:
  server.machines.close_all()
  server.server_close()
