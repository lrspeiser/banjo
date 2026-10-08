import importlib.util,json,sys,tempfile,threading,urllib.request,urllib.error
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
  status,a=req({'op':'create','declaration':{}});assert status==200 and a['ok'];key=a['session'];initial=a['state']
  _,b=req({'op':'create','declaration':{'sheet':'iron'}});other=b['session']
  _,moved=req({'op':'advance','session':key,'steps':16});assert moved['state']['time_s']>0
  _,still=req({'op':'snapshot','session':other});assert still['state']['time_s']==0,'sessions shared'
  for steps in [0,17,True,-1]:assert req({'op':'advance','session':key,'steps':steps})[0]==400
  assert req({'op':'create','declaration':{'bogus':1}})[1]['ok'] is False
  for iterations in [15,257,96.5,True,'96']:
   assert req({'op':'create','declaration':{'solver_iterations':iterations}})[1]['ok'] is False
  _,unchanged=req({'op':'snapshot','session':key});assert unchanged['state']==moved['state'],'refusal mutated native state'
  with urllib.request.urlopen(base+'/api/log/'+key) as r:rows=[json.loads(x) for x in r.read().decode().splitlines()]
  assert rows[0]['native_sha256'] and rows[0]['assets'];assert any(r.get('response',{}).get('state')==moved['state'] for r in rows),'record differs from rendered response'
  assert req({'op':'close','session':key})[1]['ok'];assert req({'op':'snapshot','session':key})[0]==400
  print('PASS gateway: new routes, isolated native sessions, bounded commands, refusal state, exact persistent records and close')
 finally:
  for s in server.sessions.values():s.close()
  server.shutdown();server.server_close()
