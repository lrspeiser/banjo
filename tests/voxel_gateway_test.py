import hashlib,importlib.util,json,sys,tempfile,threading,urllib.request,urllib.error
from pathlib import Path
spec=importlib.util.spec_from_file_location('voxel_gateway',Path(__file__).resolve().parents[1]/'scripts/voxel-lab.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as folder:
 server=m.Server(('127.0.0.1',0),Path(sys.argv[1]).resolve(),Path(folder));threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
 def req(data):
  try:
   with urllib.request.urlopen(urllib.request.Request(base+'/api/world',json.dumps(data).encode(),{'Content-Type':'application/json'})) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 try:
  with urllib.request.urlopen(base+'/world.html') as r:assert r.url==base+'/';assert b'Voxel impact world' in r.read()
  with urllib.request.urlopen(base+'/api/checkpoint') as r:
   build=json.load(r);assert r.headers['Cache-Control']=='no-store'
  assert build['native_sha256']==hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()
  assert build['native_verified']==(build['checkpoint']['native_sha256']==build['native_sha256'])
  assert len(build['website_revision'])==40 and type(build['local_changes']) is bool
  checkpoint_path=server.checkpoint_path;stale=dict(build['checkpoint']);stale['native_sha256']='0'*64
  server.checkpoint_path=Path(folder)/'stale.json';server.checkpoint_path.write_text(json.dumps(stale))
  with urllib.request.urlopen(base+'/api/checkpoint') as r:assert json.load(r)['native_verified'] is False,'stale executable advertised as verified'
  server.checkpoint_path=checkpoint_path
  status,a=req({'op':'create','declaration':{}});assert status==200 and a['ok'];key=a['session'];initial=a['state']
  _,b=req({'op':'create','declaration':{'sheet':'iron'}});other=b['session']
  _,moved=req({'op':'advance','session':key,'steps':16});assert moved['state']['time_s']>0
  _,still=req({'op':'snapshot','session':other});assert still['state']['time_s']==0,'sessions shared'
  for steps in [0,17,True,-1]:assert req({'op':'advance','session':key,'steps':steps})[0]==400
  assert req({'op':'create','declaration':{'bogus':1}})[1]['ok'] is False
  for iterations in [15,257,96.5,True,'96']:
   assert req({'op':'create','declaration':{'solver_iterations':iterations}})[1]['ok'] is False
  for law in ['invented',True,96,None]:
   assert req({'op':'create','declaration':{'face_law':law}})[1]['ok'] is False
  _,experimental=req({'op':'create','declaration':{'face_law':'log-gradient','ball_enabled':False}})
  assert experimental['ok'] and experimental['state']['qualification']['face_law']=='log-gradient'
  assert not experimental['state']['qualification']['calibrated']
  assert req({'op':'close','session':experimental['session']})[1]['ok']
  _,centered=req({'op':'create','declaration':{'face_law':'centered-log-gradient','ball_enabled':False}})
  assert centered['ok'] and centered['state']['qualification']['face_law']=='centered-log-gradient'
  assert not centered['state']['qualification']['calibrated']
  _,centered_step=req({'op':'advance','session':centered['session'],'steps':16})
  assert centered_step['ok'] and centered_step['state']['time_s']>0
  assert req({'op':'close','session':centered['session']})[1]['ok']
  assert initial['qualification']['face_law']=='native-motor','default silently changed to experimental law'
  assert initial['qualification']['contact_law']=='material-restitution','default contact response silently changed'
  for law in ['invented',True,96,None]:
   assert req({'op':'create','declaration':{'contact_law':law}})[1]['ok'] is False
  _,unilateral=req({'op':'create','declaration':{'contact_law':'resolved-deformation','ball':'glass'}})
  assert unilateral['ok'] and unilateral['state']['qualification']['contact_law']=='resolved-deformation'
  assert not unilateral['state']['qualification']['calibrated']
  assert req({'op':'close','session':unilateral['session']})[1]['ok']
  assert req({'op':'create','declaration':{'contact_law':'midpoint-unilateral'}})[1]['ok'] is False
  _,midpoint=req({'op':'create','declaration':{'contact_law':'midpoint-unilateral','face_law':'centered-log-gradient','ball_enabled':False}})
  assert midpoint['ok'] and midpoint['state']['qualification']['contact_law']=='midpoint-unilateral'
  assert not midpoint['state']['qualification']['calibrated']
  assert req({'op':'close','session':midpoint['session']})[1]['ok']
  assert req({'op':'create','declaration':{'contact_law':'midpoint-block-friction'}})[1]['ok'] is False
  _,block=req({'op':'create','declaration':{'contact_law':'midpoint-block-friction','face_law':'centered-log-gradient','ball_enabled':False}})
  assert block['ok'] and block['state']['qualification']['contact_law']=='midpoint-block-friction'
  assert not block['state']['qualification']['calibrated']
  assert req({'op':'advance','session':block['session'],'steps':16})[1]['ok']
  assert req({'op':'close','session':block['session']})[1]['ok']
  _,unchanged=req({'op':'snapshot','session':key});assert unchanged['state']==moved['state'],'refusal mutated native state'
  with urllib.request.urlopen(base+'/api/log/'+key) as r:rows=[json.loads(x) for x in r.read().decode().splitlines()]
  assert rows[0]['native_sha256'] and rows[0]['assets'];assert any(r.get('response',{}).get('state')==moved['state'] for r in rows),'record differs from rendered response'
  assert rows[0]['checkpoint']['native_sha256']==rows[0]['native_sha256'],'session provenance differs from build badge'
  assert rows[0]['checkpoint']['checkpoint']['physics_revision']==build['checkpoint']['physics_revision']
  assert req({'op':'close','session':key})[1]['ok'];assert req({'op':'snapshot','session':key})[0]==400
  print('PASS gateway: new routes, isolated native sessions, bounded commands, refusal state, exact persistent records and close')
 finally:
  for s in server.sessions.values():s.close()
  server.shutdown();server.server_close()
