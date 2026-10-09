"""Actual native pipeline parity plus deliberately delayed control-latency probe."""
import copy,gzip,hashlib,importlib.util,json,queue,sys,tempfile,threading,time,urllib.request,urllib.error
from pathlib import Path
spec=importlib.util.spec_from_file_location('voxel_pipeline',Path(__file__).resolve().parents[1]/'scripts/voxel-lab.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def physical(state):
 state=copy.deepcopy(state);state['diagnostics'].pop('profile');state['diagnostics'].pop('max_step_wall_ms');return state
with tempfile.TemporaryDirectory() as folder:
 # Exact archival codec: types, signed zero, deletions and list resizing are
 # retained; a long repeated history must not exhaust the old full-row bound.
 old={'removed':1,'zero':-0.0,'kind':1,'cells':[{'id':i,'v':[1.,2.,3.]} for i in range(8)]}
 new={'zero':0.0,'kind':True,'cells':[{'id':i,'v':[1.,float(i),3.]} for i in range(8)],'added':[1,2]}
 assert not m.same_record(old,new)
 assert m.same_record(m.apply_record_patch(old,m.record_patch(old,new)),new)
 resized=dict(new,cells=new['cells'][:3])
 assert m.same_record(m.apply_record_patch(new,m.record_patch(new,resized)),resized)
 journal=object.__new__(m.Session);journal.record_lock=threading.Lock();journal.path=Path(folder)/'codec.jsonl.bz2';journal.bytes=journal.uncompressed_bytes=0;journal.previous_record=None
 payload={'retained':'x'*3_000_000,'tick':0};journal.write(payload)
 for tick in range(1,101):payload['tick']=tick;journal.write(payload)
 assert journal.uncompressed_bytes<3_100_000 and journal.bytes<100_000,'repeated full states exhausted bounded archive'
 count=0
 for line in journal.iter_log():
  row=json.loads(line);assert row=={'retained':'x'*3_000_000,'tick':count};count+=1
 assert count==101,'lossless streaming export lost records'
 assert journal.path.read_bytes().startswith(b'BZh'),'new persistent archive uses the wrong codec'
 # A long high-drop journal may pass the former limits, but remains bounded.
 # Counter injection tests the boundary without allocating hundreds of MB.
 journal.bytes=32_000_000;journal.uncompressed_bytes=256_000_000
 journal.write(payload)
 assert journal.bytes>32_000_000 and journal.uncompressed_bytes>256_000_000
 length=journal.path.stat().st_size;previous=copy.deepcopy(journal.previous_record)
 for field,limit in [('bytes',m.JOURNAL_COMPRESSED_LIMIT),('uncompressed_bytes',m.JOURNAL_ENCODED_LIMIT)]:
  saved=getattr(journal,field);setattr(journal,field,limit)
  try:journal.write({'overflow':field});assert False,'journal capacity silently exceeded'
  except ValueError as e:assert 'record limit' in str(e)
  assert journal.path.stat().st_size==length and m.same_record(journal.previous_record,previous),'refused record corrupted archive'
  setattr(journal,field,saved)
 # Completed independent members are readable while the session is open;
 # exact signed-zero/type/list history also survives the archive boundary.
 journal.write(old);journal.write(new);journal.write(resized)
 tail=list(m.deque((json.loads(x) for x in journal.iter_log()),maxlen=3))
 assert all(m.same_record(a,b) for a,b in zip(tail,[old,new,resized]))
 # Previously persisted gzip/replacement records remain readable.
 legacy=object.__new__(m.Session);legacy.record_lock=threading.Lock();legacy.path=Path(folder)/'legacy.jsonl.gz'
 first=(json.dumps(old)+'\n').encode();second=(json.dumps({'record_codec':'banjo.exact-replacements.v1','patch':m.record_patch(old,new)})+'\n').encode()
 legacy.path.write_bytes(gzip.compress(first)+gzip.compress(second))
 restored=[json.loads(x) for x in legacy.iter_log()]
 assert m.same_record(restored[0],old) and m.same_record(restored[1],new),'old archive compatibility lost'
 print('PASS exact archival replacements: typed/signed-zero history and 303 MB streamed under storage bounds',flush=True)
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
  # Native scenes are real. Only delivery is withheld, never a force, pose or
  # constitutive result. An unanswered command has no admitted candidate.
  class InterruptedOutput:
   def __init__(self,original,eof=False):self.original=original;self.eof=eof
   def put(self,line):self.original.put(line)
   def get(self,timeout):
    if self.eof:return None
    time.sleep(timeout);raise queue.Empty
  survivor=req({'op':'create','declaration':{'sheet':'iron'}});assert survivor['ok'];other=survivor['session']
  for mode in ['manual','stream','eof']:
   created=req({'op':'create','declaration':{'sheet':'glass'}});assert created['ok'];key=created['session'];session=server.sessions[key]
   accepted=req({'op':'advance','session':key,'steps':2});assert accepted['ok']
   pending=[]
   if mode=='stream':
    # A genuine accepted batch waiting for its 30 Hz publication boundary.
    completed=session.call({'op':'advance','steps':2},record=False);assert completed['ok']
    with session.condition:session.current=completed;session.current_at=time.monotonic();session.pending_commands=[2]
    accepted=completed;pending=[2]
   state=copy.deepcopy(accepted['state']);pose_at=session.current_at
   session.response_timeout_s=.05;session.output=InterruptedOutput(session.output,eof=mode=='eof')
   started=time.monotonic()
   if mode=='stream':
    assert req({'op':'play','session':key,'running':True,'target_time_s':.1})['ok']
    while True:
     failed=frame(key)
     if not failed['pipeline']['calculating'] and not failed['pipeline']['running']:break
     assert time.monotonic()-started<3,'delivery failure did not stop the worker'
   else:failed=req({'op':'advance','session':key,'steps':1})
   assert time.monotonic()-started<3,'delivery stop exceeded bounded termination'
   assert not failed['ok'] and not session.closed and session.proc.poll() is not None
   assert m.same_record(failed['state'],state),'unanswered calculation changed the displayed scene'
   assert session.current_at==pose_at,'terminal publication refreshed a stale physics pose'
   detail=failed['delivery_failure'];assert detail['candidate_available'] is False and detail['unfinished_request'] is True
   assert detail['reason']==('process_stopped' if mode=='eof' else 'timeout')
   assert detail['last_delivered_time_s']==state['time_s'] and detail['request']['op']=='advance'
   inspected=frame(key);assert not inspected['ok'] and m.same_record(inspected['state'],state)
   assert inspected['pipeline']['status']=='native stopped' and inspected['pipeline']['published_state_age_ms']>0
   assert not req({'op':'play','session':key,'running':True,'target_time_s':.1})['ok']
   assert not req({'op':'advance','session':key,'steps':1})['ok']
   rows=[json.loads(x) for x in session.iter_log()];terminal=[x for x in rows if 'delivery' in x]
   assert len(terminal)==1 and terminal[0]['delivery']==detail and m.same_record(terminal[0]['response']['state'],state)
   batches=[x for x in rows if x.get('request',{}).get('op')=='advance_batch']
   assert [s for x in batches for s in x['request']['steps']]==pending,'unfinished request recorded as accepted steps'
   time.sleep(.06);assert m.same_record(frame(key)['state'],state),'late native output replaced the retained pose'
   assert req({'op':'advance','session':other,'steps':1})['ok'],'one failed calculation stopped another world'
   assert req({'op':'close','session':key})['ok'] and session.closed
   print('PASS interrupted native delivery:',mode,'exact retained scene, separate unanswered command, inspectable record and isolated termination',flush=True)
  assert req({'op':'close','session':other})['ok']
 finally:
  for session in list(server.sessions.values()):session.close()
  server.shutdown();server.server_close()
