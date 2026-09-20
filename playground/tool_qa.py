"""Recorded product-use trials over the existing native ground-work model.

Every case uses the same one-piece pick, bounded hand and swing. Material and
ground are controlled inputs. A missing rock law is an unsupported outcome,
never a successful mining test. The user's live room is never opened or stepped.
"""
from pathlib import Path
import math
import threading
import time
import uuid

import fracture_lab
import material_qa as artifacts
import mechanics_qa
from physics_trials import TrialSession, DT

SCHEMA = "banjo.tool-qa.v1"
CELL = .04
_LOCK = threading.Lock()
LIMITATIONS = [
    "A one-piece reference pick, not the user's selected Workshop assembly or a rated head-handle joint.",
    "The same 800 N hand and 60 N m wrist drive every swing; actual impact speed depends on mass and contact.",
    "Ground-work-v1 is an experimental dry-soil model. Hard-point rock excavation and wet soil are unsupported.",
    "Tool condition comes from native state. Pending detailed damage stops as unresolved, never as survived.",
    "40 mm tool cells and 100 mm terrain columns; no calibration, wear, timestep convergence or full energy-closure claim.",
]


def cases():
    return [{"id": f"pick-{material}-{ground}", "material": material, "ground": ground,
             "title": f"{material.title()} pick into {ground}"}
            for ground in ("soil", "rock") for material in ("oak", "glass", "iron")]


def select(ids=None):
    known = {c["id"]: c for c in cases()}
    if ids is None:
        return list(known.values())
    if (not isinstance(ids, list) or not ids or len(ids) > len(known)
            or any(not isinstance(i, str) or i not in known for i in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("Use unique case_ids from the tool QA catalog")
    return [known[i] for i in ids]


def recipe(case):
    top = .4 if case["ground"] == "soil" else 0
    spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": CELL,
        "terrain": {"generate": {"kind": "flat", "nx": 48, "nz": 48, "cell_m": .1,
            "soil_m": top, "sand_m": 0., "discharge_m3_s": 0.}},
        "bodies": [
            {"name": "pick", "join": "pick", "shape": "box", "material": case["material"],
             "size_mm": [800,40,40], "center_mm": [0,1000*(top+1.02),20]},
            {"name": "pick arm", "join": "pick", "shape": "box", "material": case["material"],
             "size_mm": [40,280,40], "center_mm": [380,1000*(top+.86),20]}]})
    grip = [-.36,top+1.02,.02]
    commands = [
        {"op": "hand", "strength_n": 800, "torque_n_m": 60, "mass_kg": 1},
        {"op": "tool_point", "body": "pick", "tip": [.38,top+.72,.02], "pointing": [0,-1,0],
         "width_m": .04, "thickness_m": .04, "length_m": .2, "angle_deg": 30, "grip": grip},
        {"op": "wield", "name": "pick", "grip": grip},
        {"op": "strike", "at": [.3,top,.02], "shoulder": [-.9,top+1.45,.02],
         "speed_m_s": 2, "raise_deg": 110, "give_up_s": 4}]
    return {"spec": spec, "commands": commands, "dt_s": DT, "duration_s": 4.5,
            "ground_height_m": top, "note": "speed_m_s is the bounded grip's target speed, not an imposed tool velocity"}


def catalog(engine=None):
    exe = mechanics_qa.binary(engine)
    return {"schema": SCHEMA, "cases": cases(), "limitations": LIMITATIONS,
            "suite_hash": artifacts.digest([recipe(c) for c in cases()]),
            "engine_available": bool(exe and exe.is_file())}


def rotate(q, v):
    w,x,y,z = q
    t = [2*(y*v[2]-z*v[1]), 2*(z*v[0]-x*v[2]), 2*(x*v[1]-y*v[0])]
    return [v[0]+w*t[0]+y*t[2]-z*t[1], v[1]+w*t[1]+z*t[0]-x*t[2],
            v[2]+w*t[2]+x*t[1]-y*t[0]]


def run_case(engine, case, directory, cancel=None):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    request = recipe(case)
    artifacts.write_json(directory/"request.json", request)
    cancel = cancel or threading.Event()
    result = {**case, "schema": SCHEMA, "status": "failed", "limitations": LIMITATIONS,
              "request_hash": artifacts.digest(request)}
    frames, geometry, events = [], [], []
    session = None
    started = time.monotonic()
    try:
        session = TrialSession(Path(engine), request["spec"], directory,
                               cancel=cancel, deadline=started+45)
        initial = session.send(op="poses")
        if len(initial["bodies"]) != 1 or initial["bodies"][0]["name"] != "pick":
            raise ValueError("Native tool was not fused as declared")
        body = initial["bodies"][0]
        cells = body.get("cells_local_m", [])
        if len(cells) != 27:
            raise ValueError("Native pick does not contain its declared 27 cells")
        rgba = int(body["color_rgba"], 16)
        geometry = [{"id": f"pick-cell-{i}", "shape": "box", "dimensions_m": [CELL]*3,
                     "color_rgba": rgba, "material_id": case["material"]} for i in range(len(cells))]
        # This is the actual flat terrain surface, drawn as a thin section for
        # a clear side view of penetration. It is display geometry, not a body.
        geometry.append({"id": "ground-section", "shape": "box", "dimensions_m": [2.4,.04,.8],
                         "color_rgba": 0x766047ff if case["ground"] == "soil" else 0x7c878cff})
        top = request["ground_height_m"]
        def capture(state):
            current = state["bodies"]
            if len(current) != 1 or current[0]["name"] != "pick":
                raise ValueError("Tool topology changed before a resolved recording was available")
            b = current[0]
            if abs(b["mass_kg"]-body["mass_kg"]) > 1e-8:
                raise ValueError("Tool mass changed")
            q = b["orientation_wxyz"]
            poses = [{"id": f"pick-cell-{i}", "position_m": [a+c for a,c in zip(rotate(q,v),b["position_m"])],
                      "orientation_wxyz": q} for i,v in enumerate(cells)]
            poses.append({"id": "ground-section", "position_m": [0,top-.02,0], "orientation_wxyz": [1,0,0,0]})
            frames.append({"time_s": state["t"], "poses": poses, "phase": "native tool swing"})
        capture(initial)
        for command in request["commands"]:
            answer = session.send(**command)
            events.append({"time_s": session.state["t"], "command": command, "reply": answer})
        max_force = 0
        for step in range(round(request["duration_s"]/DT)):
            if cancel.is_set():
                raise ValueError("cancelled")
            before = session.state["t"]
            state = session.send(op="step", dt=DT, n=1)
            if state.get("breakable") or state.get("working_on") or state.get("stepped_back"):
                result["status"] = "unresolved"
                raise ValueError("Native tool damage requires detailed refinement; survival is unresolved")
            if abs(state["t"]-before-DT) > 1e-7:
                raise ValueError("Native time did not advance")
            max_force = max(max_force, math.dist((state.get("hand") or {}).get("force_n", [0,0,0]), [0,0,0]))
            if step % 2 == 1:
                capture(session.state)
        native = session.send(op="ground_work")
        meetings = native.get("ground_work", [])
        if not meetings:
            raise ValueError("The tool never contacted the target ground")
        if any(w["ground"] != case["ground"] for w in meetings):
            raise ValueError("The tool contacted the wrong ground")
        if max_force > 800.001:
            raise ValueError("Hand exceeded its 800 N force limit")
        unsupported = any(not w["supported"] for w in meetings)
        deepest = max(meetings, key=lambda w:w["depth_m"])
        if case["ground"] == "soil" and (unsupported or not .03 <= deepest["depth_m"] <= .2+CELL):
            raise ValueError("Soil trial did not enter by 30 mm within the point length plus one cell")
        if case["ground"] == "rock" and any(w["depth_m"] != 0 or w["loosened_kg"] != 0 for w in meetings):
            raise ValueError("Rock trial claimed excavation without an implemented rock law")
        if any(math.dist([w["at_m"][k] for k in (0,2)], [.3,.02]) > .25 for w in meetings):
            raise ValueError("The point missed the intended 250 mm target radius")
        result.update(status="unsupported" if unsupported else "passed", meetings=meetings,
            measured={"depth_m": deepest["depth_m"], "work_j": sum(w["work_j"] for w in meetings),
                "closing_speed_m_s": max(w["closing_speed_m_s"] for w in meetings),
                "tool_whole": all(w["tool_whole"] for w in meetings),
                "tool_dent_mm": max(w["tool_dent_mm"] for w in meetings),
                "tool_mass_kg": body["mass_kg"], "mass_residual_kg": session.state["bodies"][0]["mass_kg"]-body["mass_kg"],
                "max_hand_force_n": max_force, "elapsed_s": session.state["t"],
                "loosened_kg": sum(w["loosened_kg"] for w in meetings)},
            outcome=("Unsupported rock excavation" if unsupported else
                     "Tool damaged" if not all(w["tool_whole"] for w in meetings) else
                     "Point entered soil" if deepest["depth_m"] > 0 else "Point stopped at rock"))
        artifacts.write_json(directory/"native-report.json", native)
    except Exception as exc:
        result.update(status="cancelled" if cancel.is_set() else result["status"], error=str(exc))
    finally:
        if session:
            session.close()
    result["wall_s"] = time.monotonic()-started
    artifacts.write_json(directory/"events.json", events)
    artifacts.write_json(directory/"playback.json", {"schema": "banjo.playback.v1",
        "status": "complete" if result["status"] in ("passed","unsupported") else "partial",
        "bodies": geometry, "frames": frames, "supports": [], "physical_response_validated": False})
    artifacts.write_json(directory/"result.json", result)
    return result


def run_suite(engine, directory, ids=None, cancel=None):
    chosen = select(ids)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = {"id": directory.name, "schema": SCHEMA, "status": "running", "total": len(chosen),
        "completed": 0, "started_unix_s": time.time(), "results": [],
        "provenance": artifacts.provenance(mechanics_qa.binary(engine)),
        "suite_hash": catalog(engine)["suite_hash"]}
    artifacts.write_json(directory/"report.json", report)
    for c in chosen:
        if cancel and cancel.is_set():
            break
        report["active_case"] = c["id"]
        artifacts.write_json(directory/"report.json", report)
        report["results"].append(run_case(engine, c, directory/c["id"], cancel))
        report["completed"] += 1
        artifacts.write_json(directory/"report.json", report)
    report.pop("active_case", None)
    states = {r["status"] for r in report["results"]}
    report["status"] = ("cancelled" if cancel and cancel.is_set() else "failed" if "failed" in states else
                        "unresolved" if "unresolved" in states else "unsupported" if "unsupported" in states else "passed")
    report["finished_unix_s"] = time.time()
    artifacts.write_json(directory/"report.json", report)
    return report


class Manager(artifacts.Manager):
    def __init__(self, app):
        super().__init__(app)
        self.root = Path(app.runs_path)/"tool-qa"

    def start(self, body):
        if not isinstance(body, dict) or set(body)-{"case_ids"}:
            raise ValueError("Tool QA accepts only case_ids")
        chosen = select(body.get("case_ids"))
        if not catalog(self.app.engine_path)["engine_available"]:
            raise ValueError("Build the native live world runner")
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("Tool QA is already running")
            self.run_id = uuid.uuid4().hex
            self.cancel_event = threading.Event()
            self.pending = {"id": self.run_id, "status": "starting", "total": len(chosen), "completed": 0, "results": []}
            folder = self.folder(self.run_id)
            def work():
                try:
                    run_suite(self.app.engine_path, folder, [c["id"] for c in chosen], self.cancel_event)
                except Exception as exc:
                    artifacts.write_json(folder/"report.json", {**self.pending, "status": "failed", "error": str(exc)})
            self.thread = threading.Thread(target=work, name="banjo-tool-qa", daemon=True)
            self.thread.start()
            return dict(self.pending)

    def case(self, run_id, case_id, artifact=None):
        select([case_id])
        if artifact not in (None, "playback", "request"):
            raise ValueError("Unknown tool QA artifact")
        return artifacts.read_json(self.folder(run_id)/case_id/((artifact or "result")+".json"))


def manager(app):
    with _LOCK:
        if not hasattr(app, "tool_qa"):
            app.tool_qa = Manager(app)
        return app.tool_qa
