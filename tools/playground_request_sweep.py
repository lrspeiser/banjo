"""Seeded live GPT -> native -> recording evaluations. Requires --execute.

Each prompt is a new request; no automatic paid retries. Outcomes distinguish
intent preservation, engine completion, numerical limits and material validity.
"""
import argparse
import json
from pathlib import Path
import random
import time
from urllib.request import Request, urlopen
import uuid


def trials(seed):
    rng = random.Random(seed)
    height = rng.choice([0.1, 0.2, 0.3])
    offset = rng.choice([0.01, 0.02, 0.03])
    pressure = rng.choice([100, 200, 300])
    spin = rng.choice([2, 4, 6])
    rows = [
        ("offset_drop", f"Drop an 80 mm iron ball from {height} m onto free rigid glass, oak and iron targets resting on ground. Targets are 0.24 by 0.36 by 0.04 m. Offset the impact by {offset} m along x, zero along z. Run 0.5 seconds, no fracture. Add Release, reset, and a height slider.", "drop_test", {"drop.heights_m": [height], "drop.impact_offset_m": [offset, 0], "drop.support": "free_on_ground", "drop.representation": "rigid"}),
        ("cube_sweep", "Compare an iron cube 60 mm on each side dropped from 0.1 and 0.3 m onto free rigid glass, oak and iron targets, each 0.2 by 0.3 by 0.02 m. Centred impact, duration 0.5 s, no fracture. Add play and height controls.", "drop_test", {"drop.projectile": "iron_cube", "drop.projectile_dimensions_m": [.06]*3, "drop.heights_m": [.1,.3], "drop.target_dimensions_m": [.2,.3,.02]}),
        ("experimental_thin", "Try an explicitly uncalibrated volumetric network experiment: an 80 mm iron ball dropping 0.05 m onto 6 mm panels of glass, oak and iron. Clamped edges, panel width 0.12 m and length 0.16 m, resolution 4 by 4 by 2, centred impact. Run 0.3 seconds. I accept unresolved diagnostic results; I am not requesting shell accuracy or realistic tempered shattering. Add play, reset, height control and components.", "drop_test", {"drop.target_dimensions_m": [.12,.16,.006], "drop.representation": "network", "drop.resolution": [4,4,2], "drop.heights_m": [.05]}),
        ("zero_gravity", f"Use a custom scene: two rigid iron cubes of dimensions 0.08 m each, at [-0.2,0.3,0] and [0.2,0.3,0]. Give velocities [1,0,0] and [-1,0,0], spin [0,{spin},0] on both, zero gravity and no ground. Run 0.4 seconds and add Play, reset and components controls.", "scene_test", {"scene.environment.gravity_m_s2": [0,0,0], "scene.environment.ground": False, "scene.objects.0.spin_rad_s": [0,spin,0], "scene.objects.0.velocity_m_s": [1,0,0], "scene.objects.1.velocity_m_s": [-1,0,0]}),
        ("low_gravity", "Create a custom scene with one rigid iron ball 0.08 m diameter at [0,0.4,0] and one rigid wood panel 0.2 by 0.2 by 0.04 m at [0.4,0.3,0], both initially stationary, identity orientation, no spin. Set gravity [0,-1.62,0], ground enabled, friction 0.3. Run 0.5 seconds. Add play and reset.", "scene_test", {"scene.environment.gravity_m_s2": [0,-1.62,0], "scene.environment.ground_friction": .3, "scene.objects.1.representation": "rigid"}),
        ("pressure", f"Run the illustrative quasistatic glass oak iron pressure reference at {pressure} MPa, resolution 4, 8 increments, smooth pressure profile. Add Watch response and pressure slider 100 to 800 MPa. No collision or fracture required.", "continuum_pressure_reference", {"pressure.peak_pressure_pa": pressure*1e6, "pressure.increments": 8, "pressure.profile": "smooth"}),
        ("unsupported_fluid", "Simulate water pouring from a jug into a bowl with free-surface splashes and realistic fluid flow. Show the actual fluid simulation.", "blocked", {}),
        ("unsupported_calibration", "Reproduce calibrated realistic shattering of a 6 mm tempered glass window from a dropped iron ball, including its manufacturing residual stress. Do not substitute a coarse uncalibrated model.", "blocked", {}),
    ]
    rng.shuffle(rows)
    return rows


def lookup(value, key):
    for part in key.split("."):
        value = value[int(part)] if isinstance(value,list) else value[part]
    return value


def equal(a,b):
    if isinstance(a,list) and isinstance(b,list): return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)): return abs(a-b)<1e-8*max(1,abs(b))
    return a==b


def run(base, seed, output, only=None):
    def api(path, body=None):
        headers = {"Content-Type":"application/json", "X-Banjo-Token": token} if body is not None else {}
        req = Request(base+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urlopen(req,timeout=100) as response: return json.load(response)
    token = ""
    token = api("/api/status")["csrf_token"]
    report = {"seed":seed,"scope":"Finite seeded prompt sample; not general capability or material validation", "trials":[]}
    for name,prompt,expected,checks in trials(seed):
        if only and name not in only: continue
        start=time.perf_counter()
        row={"name":name,"prompt":prompt,"expected":expected,"checks":checks}
        try:
            job_id=api("/api/chat",{"message":prompt,"previous_plan":None,"request_id":uuid.uuid4().hex,"auto_open":False})["job_id"]
            deadline=time.monotonic()+330
            while True:
                job=api("/api/jobs/"+job_id)
                if job["status"] in ("complete","blocked","error"): break
                if time.monotonic()>deadline: raise TimeoutError("Job exceeded sweep wait budget")
                time.sleep(.4)
            plan=job.get("plan") or {}
            mismatches=[]
            for key,value in checks.items():
                try: actual=lookup(plan,key)
                except (KeyError,IndexError,TypeError): actual=None
                if not equal(actual,value): mismatches.append({"field":key,"expected":value,"actual":actual})
            passed=(job["status"]=="blocked") if expected=="blocked" else (job["status"]=="complete" and plan.get("experiment")==expected and not mismatches and all(c.get("playback_available") for c in job.get("cases",[])) and bool(job.get("cases")))
            row.update(job_id=job_id,status=job["status"],message=job["message"],plan=plan,mismatches=mismatches,passed=passed,timing=job.get("timing"),cases=[{"status":c["status"],"playback":c.get("playback_available"),"assessment":c.get("assessment"),"wall_s":c.get("wall_s"),"inner_cases":c.get("inner_cases")} for c in job.get("cases",[])])
        except Exception as exc: row.update(passed=False,error=type(exc).__name__)
        row["wall_s"]=time.perf_counter()-start
        report["trials"].append(row)
        report["passed"]=sum(t["passed"] for t in report["trials"])
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2),encoding="utf-8")
        print(json.dumps({"name":name,"passed":row["passed"],"status":row.get("status"),"job_id":row.get("job_id"),"mismatches":row.get("mismatches",[])}),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute",action="store_true",help="Authorize the eight real model requests")
    parser.add_argument("--base",default="http://127.0.0.1:8767")
    parser.add_argument("--seed",type=int,default=60926)
    parser.add_argument("--output",type=Path,default=Path("build/experiment-sweep/results.json"))
    parser.add_argument("--only",nargs="+",help="Explicit targeted rerun; retains failed earlier artifacts separately")
    args=parser.parse_args()
    if not args.execute: parser.error("Pass --execute to run real model requests")
    result=run(args.base,args.seed,args.output,args.only)
    raise SystemExit(0 if result["passed"]==len(result["trials"]) else 1)
