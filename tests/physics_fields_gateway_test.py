"""Authenticated actual HTTP/native paths for articulated, flow and scalar fields."""
import argparse,hashlib,http.cookiejar,importlib.util,json,os,sys,tempfile,threading,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
p=argparse.ArgumentParser();p.add_argument('--library-dir',type=Path,required=True);p.add_argument('--native',type=Path,required=True);a=p.parse_args()
paths={}
for kind,stem,env in [('mechanisms','banjo_mechanisms_cpu','BANJO_MECHANISMS_LIBRARY'),('flow','banjo_flow_cpu','BANJO_FLOW_LIBRARY'),('thermal-fields','banjo_thermal_fields','BANJO_THERMAL_FIELDS_LIBRARY')]:
 path=(a.library_dir/(stem+'.dll' if os.name=='nt' else 'lib'+stem+'.so')).resolve();assert path.is_file(),path;os.environ[env]=str(path);paths[kind]=path
spec=importlib.util.spec_from_file_location('fields_gateway',ROOT/'scripts/voxel-lab.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as folder:
 server=module.Server(('127.0.0.1',0),a.native.resolve(),Path(folder),password='field-regression-only',public_host='test.example');threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def request(path,data=None,headers=None,auth=True):
  req=urllib.request.Request(base+path,None if data is None else json.dumps(data).encode(),headers or {'Content-Type':'application/json'})
  try:
   with (client.open if auth else urllib.request.urlopen)(req,timeout=45) as response:return response.status,response.read()
  except urllib.error.HTTPError as e:return e.code,e.read()
 def command(data):
  code,body=request('/api/thermal-fields',data);reply=json.loads(body);assert code==200,(code,reply);return reply
 payloads={'mechanisms':('/api/mechanisms/run',{'material':'glass','duration_s':.1,'dt_s':1/240}),'flow':('/api/flow-reference',{'declaration':{'nx':8,'nz':4,'frames':5,'duration_s':.05,'left_depth_m':.1}}),'thermal-fields':('/api/thermal-fields',{'op':'create','declaration':{}})}
 try:
  for path,_ in payloads.values():assert request(path,{},auth=False)[0]==401
  for path in ('/mechanisms','/flow','/thermal-fields'):assert request(path,auth=False)[0] in (401,200) # unauthenticated HTML may be the login form
  code,_=request('/login',{'password':'field-regression-only'});assert code==200
  for path in ('/mechanisms','/flow','/thermal-fields','/thermal-fields.js','/thermal-fields.css'):assert request(path)[0]==200
  for kind,(path,payload) in payloads.items():
   assert request(path,payload,{'Content-Type':'application/json','Origin':'https://unrelated.invalid'})[0]==400
   assert request(path,payload,{'Content-Type':'application/json','Host':'unrelated.invalid'})[0]==400
   original=server.field_libraries[kind];server.field_libraries[kind]=None
   code,body=request(path,payload);assert code==400 and b'unavailable' in body,(code,body)
   server.field_libraries[kind]=original
  code,raw=request(*payloads['mechanisms']);mechanism=json.loads(raw);assert code==200 and mechanism['schema']=='banjo-mechanism-reference-1' and len(mechanism['frames'])>1
  assert mechanism['native_sha256']==hashlib.sha256(paths['mechanisms'].read_bytes()).hexdigest()
  assert request('/api/mechanisms/run',{'duration_s':float('nan')})[0]==400
  code,raw=request(*payloads['flow']);flow=json.loads(raw);assert code==200 and flow['ok'] and len(flow['frames'])==5
  assert flow['native_sha256']==hashlib.sha256(paths['flow'].read_bytes()).hexdigest()
  assert request('/api/flow-reference',{'declaration':{'nx':0}})[0]==400
  assert request('/api/flow-reference',{'declaration':{},'unknown':1})[0]==400
  created=command({'op':'create','declaration':{'material':'ice','initial_temperature_k':273.15}});assert created['ok'];key=created['session']
  other=command({'op':'create','declaration':{'material':'glass'}});assert other['ok'];otherkey=other['session']
  assert created['state']['implementation']['binary_sha256']==hashlib.sha256(paths['thermal-fields'].read_bytes()).hexdigest()
  assert request('/api/thermal-fields',{'op':'advance','session':key,'steps':201})[0]==400
  advanced=command({'op':'advance','session':key,'steps':200});assert advanced['ok'];s=advanced['state'];assert abs(s['time_s']-10)<1e-10 and max(c['liquid_fraction'] for c in s['cells'])>0
  assert abs(s['audit']['energy_residual_j'])<1e-8
  assert command({'op':'snapshot','session':otherkey})['state']['time_s']==0
  checkpoint=command({'op':'export','session':key})['checkpoint'];reopened=command({'op':'restore','checkpoint':checkpoint});assert reopened['ok']
  assert command({'op':'export','session':reopened['session']})['checkpoint']==checkpoint
  assert request('/api/thermal-fields',{'op':'play','session':key,'running':True,'target_time_s':2})[0]==400
  refused=command({'op':'create','declaration':{'material':'iron','reaction':True}});assert not refused['ok'] and 'no name-only combustion' in refused['error']
  rows=[json.loads(row) for row in request('/api/log/'+key)[1].splitlines()]
  assert any(row.get('request',{}).get('op')=='advance' and row['response']['state']['audit']['external_heat_j']>0 for row in rows)
  for session in (key,otherkey,reopened['session']):assert command({'op':'close','session':session})['ok']
  assert command({'op':'close','session':key})['already_closed']
  print('Three real HTTP/native families: auth/host/origin, unavailable binaries, strict refusals, thermal isolation/exact restore/logs/200-step bound and unsupported scheduler passed')
 finally:
  for session in list(server.sessions.values()):session.close()
  server.shutdown();server.server_close()
