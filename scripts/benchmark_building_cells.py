"""Bounded scene-size and physical hammer-impact probe; production limits unchanged."""
import argparse,ctypes,json,os,sys,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"mcp"),str(ROOT/"playground")]
p=argparse.ArgumentParser()
p.add_argument("--engine",type=Path,required=True);p.add_argument("--spec",type=Path,required=True)
p.add_argument("--cell",type=float,default=.02);p.add_argument("--material",choices=["glass","oak","iron"],default="glass")
p.add_argument("--out",type=Path,required=True);p.add_argument("--impact",action="store_true")
p.add_argument("--grip-y",type=float,default=1.26)
p.add_argument("--fill-to-cap",action="store_true",help="Add separate anchored stock blocks to reach exactly 160000 cells at 10 mm")
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
os.environ["BANJO_LIBRARY"]=str(a.engine.resolve().parent/"banjo.dll")
import fracture_lab,live_session,world_room,room_store
# Explicit experiment budget, local to this process. No application setting changes.
fracture_lab.ALGORITHMS["lattice"]["max_cells"]=160000
spec=json.loads(a.spec.read_text());spec["cell_m"]=a.cell
for b in spec["bodies"]:
    if b["name"].endswith("pane"):b["material"]=a.material
if a.fill_to_cap:
    if a.cell!=.01:raise ValueError("the exact-cap stock layout uses 10 mm cells")
    count=fracture_lab.scene_cell_count(fracture_lab.normalise_bodies(spec["bodies"],a.cell),a.cell)
    left=160000-count;chunks=[]
    if left<0:raise ValueError("scene already exceeds the experiment cap")
    while left>=4096:chunks.append([16,16,16]);left-=4096
    for unit,base in ((256,[16,16]),(16,[16,1]),(1,[1,1])):
        n,left=divmod(left,unit)
        if n:chunks.append([*base,n])
    for i,dims in enumerate(chunks):
        size=[d*10 for d in dims]
        spec["bodies"].append({"name":"stock block "+str(i),"shape":"box","material":"oak","anchored":True,
                              "size_mm":size,"center_mm":[3000+300*i+size[0]/2,size[1]/2,size[2]/2]})
start=time.perf_counter();valid=fracture_lab.validate(spec);validation=time.perf_counter()-start
if a.fill_to_cap and valid["cells"]!=160000:raise AssertionError(valid["cells"])
(a.out/"spec.json").write_text(json.dumps(spec,indent=2))
print(json.dumps({"validated_cells":valid["cells"],"validation_s":validation}),flush=True)
live=live_session.Live();room=world_room.Room("yard");room.spec=spec
app=SimpleNamespace(live=live,room=room,engine_path=a.engine.resolve(),runs_path=a.out.resolve()/"runs",live_holder="world")
start=time.perf_counter();live.open(app,{"spec":spec});opening=time.perf_counter()-start
report={"cell_m":a.cell,"material":a.material,"cells":valid["cells"],"cap":160000,
        "validation_s":validation,"open_s":opening,"dt_s":1/240,"grip_y_m":a.grip_y,"impacts":[],"fractures":[]}
class Memory(ctypes.Structure):
    _fields_=[("cb",ctypes.c_ulong),("faults",ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in
        ("peak_working","working","quota_peak_paged","quota_paged","quota_peak_nonpaged","quota_nonpaged","pagefile","peak_pagefile","private")]
def memory():
    m=Memory();m.cb=ctypes.sizeof(m);f=ctypes.WinDLL("psapi").GetProcessMemoryInfo
    f.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    if not f(int(live.session._process._handle),ctypes.byref(m),m.cb):raise ctypes.WinError()
    return {"working_mb":m.working/1048576,"peak_working_mb":m.peak_working/1048576,"private_mb":m.private/1048576}
def act(op,**kw):return live.act({"session":live.session.id,"op":op,**kw})
def mass():
    # This sums reported dynamic mass; anchored scenery reports zero.
    return sum(b["mass_kg"] for b in live.session.state["bodies"])
def step(n=4):
    r=act("step",dt=1/240,n=n)
    report["impacts"].extend(r.get("impacts",[]))
    if r.get("finished"):report["fractures"].append({k:r.get(k) for k in ("t","finished","pieces","outcome")})
    if r.get("breakable") and not r.get("working_on"):act("fracture",name=r["breakable"][0],wait=False)
    return r
try:
    report["memory_open"]=memory();report["mass_before_kg"]=mass()
    act("wield",name="sledgehammer",grip=[-.75,a.grip_y,.65])
    start=time.perf_counter()
    for _ in range(30):step()
    report["half_second_wall_s"]=time.perf_counter()-start
    report["memory_settled"]=memory()
    if a.impact:
        hand=live.session.state["hand"];report["work_before_j"]=hand.get("work_j")
        grip=hand["grip_m"];end=[grip[0],grip[1],grip[2]-1.2]
        act("stroke",path=[grip,end],speed_m_s=8,accel_m_s2=60,lead_m=.1,let_go=False,give_up_s=5)
        start=time.perf_counter();deadline=start+45
        while time.perf_counter()<deadline:
            step()
            if not live.session.state.get("hand",{}).get("stroking") and not live.session.state.get("working_on") and not live.session.state.get("breakable"):break
            if live.session.state.get("working_on"):time.sleep(.01)
        report["impact_wall_s"]=time.perf_counter()-start
        report["hand_after"]=live.session.state.get("hand")
        report["pending"]=live.session.state.get("working_on")
        act("cancel_stroke")
    report["memory_final"]=memory();report["mass_after_kg"]=mass()
    report["t_s"]=live.session.state.get("t");report["body_count"]=len(live.session.state["bodies"])
    report["bodies"]=[{k:b[k] for k in ("name","material","mass_kg","position_m","dent_mm") if k in b} for b in live.session.state["bodies"]]
    saved,why=live.snapshot();report["save_refused"]=why
    if saved:
        (a.out/"snapshot.json").write_text(json.dumps(saved))
        room.world_record=saved;room_store.RoomStore(a.out/"rooms").save(room)
    (a.out/"report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ("impacts","bodies")}),flush=True)
finally:live.shutdown()
