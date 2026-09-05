import argparse,json,subprocess,time,platform,math
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True);parser.add_argument('--output',default='build/platform-evidence');args=parser.parse_args()
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
exe=args.exe
rows=[]
for path in sorted(Path('assets/platform').glob('*.json')):
 s=json.loads(path.read_text());ref=s['backend']=='bonded-reference-v2'
 steps=720 if 'isolated' in path.name else (24 if ref else 240)
 start=time.perf_counter()
 run=subprocess.run([exe,'--run',str(path),str(steps)],capture_output=True,text=True)
 try:r=json.loads(run.stdout)
 except Exception:print(run.stdout,run.stderr,flush=True);raise
 (out/path.name).write_text(json.dumps(r,indent=2))
 ok=run.returncode==0
 if ref and 'strong-impact' in path.name:ok &= bool(r.get('fracture_events')) if 'glass' in path.name else not r.get('fracture_events')
 if ref and ('gentle-impact' in path.name or 'isolated' in path.name):ok &= not r.get('fracture_events')
 if 'colliding-bodies' in path.name:ok &= r.get('ball_contact_callbacks',0)>0
 ok &= len(r.get('objects',[]))==len(s['objects'])
 if 'isolated' in path.name:
  final=r['objects'][0];initial=s['objects'][0]
  ok &= math.dist(final['position_m'],initial['position_m'])>.01 and math.sqrt(sum(c*c for c in final['spin_rad_s']))>.1
 if 'free-flight' in path.name:
  for a,b in zip(s['objects'],r['objects']):
   expected=[x+v*steps*s['fixed_dt_s'] for x,v in zip(a['position_m'],a['velocity_m_s'])]
   ok &= math.dist(expected,b['position_m'])<1e-5
 if ref:ok &= abs(r.get('energy_residual_j',1e99))<=.01*max(abs(r.get('initial_energy_j',0)),1e-6)
 if not ref:ok &= all(all(math.isfinite(c) and abs(c)<1000 for c in b['position_m']) for b in r.get('objects',[]))
 row=dict(scene=path.stem,passed=bool(ok),steps=steps,process_wall_s=time.perf_counter()-start,load_ms=r.get('load_wall_ms'),performance=r.get('performance'),fractures=len(r.get('fracture_events',[])),callbacks=r.get('ball_contact_callbacks'),error=r.get('error',r.get('fault')))
 rows.append(row);print(json.dumps(row),flush=True)
summary=dict(machine=platform.platform(),processor=platform.processor(),results=rows)
(out/'summary.json').write_text(json.dumps(summary,indent=2))
raise SystemExit(0 if all(r['passed'] for r in rows) else 1)
