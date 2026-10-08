"""Actual native pipeline parity plus deliberately delayed control-latency probe."""
import copy,hashlib,importlib.util,json,sys,tempfile,threading,time,urllib.request,urllib.error
from pathlib import Path
spec=importlib.util.spec_from_file_location('voxel_pipeline',Path(__file__).resolve().parents[1]/'scripts/voxel-lab.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def physical(state):
 state=copy.deepcopy(state);state['diagnostics'].pop('profile');state['diagnostics'].pop('max_step_wall_ms');return state
with tempfile.TemporaryDirectory() as folder:
 server=m.Server(('127.0.0.1',0),Path(sys.argv[1]).resolve(),Path(folder));threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
 def req(data):
  try:
   with urllib.request.urlopen(urllib.request.Request(base+'/api/world',json.dumps(data).encode(),{'Content-Type':'application/json'}),timeout=10) as r:return json.load(r)
  except urllib.error.HTTPError as e:return json.load(e)
 def frame(key,after=0,wait=200):return req({'op':'frame','session':key,'after':after,'wait_ms':wait})
 try:
  for material in ['glass','oak','iron','ice']:
   keys=[]
   for _ in range(2):
    r=req({'op':'create','declaration':{'sheet':material}});assert r['ok'];keys.append(r['session'])
   direct,stream=keys
   for _ in range(6):
    reference=req({'op':'advance','session':direct,'steps':16});assert reference['ok']
    assert reference['frame_id']>0 and reference['pipeline']['published_state_age_ms']<100
    assert not reference['pipeline']['calculating'],'manual reply leaves controls waiting for a nonexistent batch'
   started=req({'op':'play','session':stream,'running':True,'target_time_s':.1});assert started['ok']
   after=0;deadline=time.monotonic()+8;seq=[]
   while True:
    actual=frame(stream,after);assert actual['ok'];assert actual['frame_id']>=after;after=actual['frame_id'];seq.append(after)
    assert actual['pipeline']['buffered_frames']==1
    metrics=actual['pipeline'];assert 0<=metrics['batch_sample_count']<=metrics['batch_sample_limit']==256
    assert 0<=metrics['native_batch_p95_ms']<=metrics['max_native_batch_ms']
    assert metrics['published_state_age_ms']>=metrics['current_state_age_ms']>=0
    assert 0<metrics['journal_compressed_bytes']<metrics['journal_uncompressed_bytes']
    if not actual['pipeline']['running'] and not actual['pipeline']['calculating']:break
    assert time.monotonic()<deadline,'pipeline stalled'
   assert physical(actual['state'])==physical(reference['state']),'scheduler changed native physics: '+material
   archive=server.sessions[stream];rows=[json.loads(x) for x in archive.read_log().decode().splitlines()];batches=[x for x in rows if x.get('request',{}).get('op')=='advance_batch']
   assert archive.path.stat().st_size==archive.bytes<archive.uncompressed_bytes,'journal compression/byte bounds differ'
   assert sum(sum(x['request']['steps']) for x in batches)==96,'archive lost native replay commands'
   assert batches[-1]['response']['state']==actual['state'],'rendered frame differs from archive'
   assert rows[0]['native_sha256']==hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()
   print('PASS actual native stream/reference parity:',material,'96 ticks',len(batches),'published frames',flush=True)
   for key in keys:assert req({'op':'close','session':key})['ok']
  r=req({'op':'create','declaration':{}});key=r['session'];session=server.sessions[key];original=session.call;entered=threading.Event()
  def delayed(command,record=True):
   if command['op']=='advance':entered.set();time.sleep(.3)
   return original(command,record)
  session.call=delayed
  assert req({'op':'play','session':key,'running':True,'target_time_s':.1})['ok'];assert entered.wait(3)
  started=time.monotonic();paused=req({'op':'play','session':key,'running':False,'target_time_s':2});latency=time.monotonic()-started
  assert paused['ok'] and not paused['pipeline']['running'];assert latency<.15,'Pause waited for the artificial 300 ms native delay'
  assert not req({'op':'advance','session':key,'steps':1})['ok'],'manual stepping raced an in-flight batch'
  while True:
   stopped=frame(key)
   if not stopped['pipeline']['calculating']:break
  t=stopped['state']['time_s'];assert 0<t<.1
  assert stopped['pipeline']['native_batch_p95_ms']>=300,'injected native delay missing from latency measurement'
  assert stopped['pipeline']['batch_sample_count']==1,'pause measured more than its one draining batch'
  time.sleep(.1);assert frame(key)['state']==stopped['state'],'pause continued simulation or changed metrics in the state'
  assert frame(key)['pipeline']['published_state_age_ms']>=100,'paused pose age not measured'
  # Quantile is nearest-rank on a bounded rolling window, not an unbounded
  # history. Injecting sample values exercises measurement only, no physics.
  with session.condition:
   session.batch_samples.extend(i/1000 for i in range(300));session.max_batch_s=.299
  measured=frame(key)['pipeline'];assert measured['batch_sample_count']==256
  assert abs(measured['native_batch_p95_ms']-287)<1e-9,'bounded p95 window/rank is wrong'
  assert not req({'op':'play','session':key,'running':True,'target_time_s':.10001})['ok'],'off-tick target accepted'
  for value in [True,-1,251]:assert not req({'op':'frame','session':key,'after':0,'wait_ms':value})['ok']
  print('PASS delayed-native pause latency',round(latency*1000,2),'ms; in-flight batch drains once, stable pause and bounded commands',flush=True)
  assert req({'op':'close','session':key})['ok']
 finally:
  for session in list(server.sessions.values()):session.close()
  server.shutdown();server.server_close()
