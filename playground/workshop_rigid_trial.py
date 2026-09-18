"""An isolated native rigid-motion test of the selected continuous-size product.

No live-room state, inventory or saved simulation is changed. The subprocess
must advertise/accept precise compound geometry; an old binary fails closed.
This is NOT a lattice stress or fracture test, and never returns a survival pass.
"""
from __future__ import annotations

import json
from math import isclose, sqrt
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from mcp import workshop_rigid, workshop_visual
import workshop_recording


def _engine(app) -> Path:
    said = getattr(app, "platform_engine_path", None)
    if said is None:
        original = Path(getattr(app, "engine_path", "banjo_platform_cli"))
        said = original if original.stem == "banjo_platform_cli" else original.with_name("banjo_platform_cli" + original.suffix)
    path = Path(said).resolve()
    if not path.is_file():
        raise ValueError("Build banjo_platform_cli with precise-rigid-compound support to run this test; no substitute simulation was run")
    return path


def _verify(artifact, package, result):
    if result.get("fault") or result.get("state_valid") is not True:
        raise ValueError("The native rigid test did not report a valid physical state")
    native = result.get("precise_rigid_bodies") or []
    if len(native) != 1 or native[0].get("id") != 1 or native[0].get("stored_cells") != 0:
        raise ValueError("Native engine did not preserve the selected zero-lattice rigid representation")
    body = native[0]
    if body.get("collision_boxes") != len(artifact["components"]):
        raise ValueError("Native collision shape count differs from the selected design")
    for key in ("mass_kg", "native_mass_kg"):
        if not isclose(float(body.get(key, 0)), artifact["mass_kg"], rel_tol=5e-6, abs_tol=1e-10):
            raise ValueError("Native material-derived rigid mass does not match the selected design")
    tensor = body.get("inertia_local_kg_m2")
    if not isinstance(tensor,list) or len(tensor)!=3 or any(not isinstance(row,list) or len(row)!=3 for row in tensor):
        raise ValueError("Native rigid inertia tensor is missing")
    for a in range(3):
        for b in range(3):
            if not isclose(tensor[a][b],artifact["inertia_kg_m2"][a][b],rel_tol=1e-9,abs_tol=1e-12):
                raise ValueError("Native rigid inertia differs from the source geometry")
    trace = result.get("trace") or {}
    frames = trace.get("frames") or []
    if trace.get("schema") != "banjo.rigid-trace.v1" or trace.get("interpolated") is not False or len(frames)<2:
        raise ValueError("The engine did not return an actual rigid-motion trace")
    if frames[0].get("t_s") != 0:
        raise ValueError("Native trace has no initial geometry verification frame")
    initial = frames[0].get("bodies") or []
    if len(initial) != len(artifact["components"]):
        raise ValueError("Native trace dropped design components")
    by_id = {b.get("element_id"):b for b in initial}
    if set(by_id) != set(range(len(initial))):
        raise ValueError("Native trace component identifiers are not complete and unique")
    placed_com = package["objects"][0]["position_m"]
    for i, part in enumerate(artifact["components"]):
        actual = by_id[i]
        if actual.get("object_id") != 1 or actual.get("shape")!="box" or actual.get("material")!=artifact["material"]:
            raise ValueError("Native shape/material does not match the selected product")
        if len(actual.get("dimensions_m",[]))!=3 or len(actual.get("position_m",[]))!=3:
            raise ValueError("Native shape dimensions or position are missing")
        for a in range(3):
            if not isclose(actual["dimensions_m"][a],part["dimensions_m"][a],rel_tol=0,abs_tol=1e-12):
                raise ValueError("Native rigid shape dimensions were altered")
            if not isclose(actual["position_m"][a],placed_com[a]+part["center_local_m"][a],rel_tol=0,abs_tol=1e-7):
                raise ValueError("Native rigid shape placement was altered")
    return frames


def run(app: Any, design, config: Any) -> dict[str, Any]:
    if not isinstance(config,dict) or set(config)-{"duration_s","drop_height_m","horizontal_speed_m_s","record_trace"}:
        raise ValueError("rigid_motion accepts duration_s, drop_height_m, horizontal_speed_m_s and record_trace only")
    keep = config.get("record_trace",True)
    if not isinstance(keep,bool):
        raise ValueError("record_trace must be a boolean")
    duration = workshop_visual._number(config.get("duration_s",2),"duration_s",.1,5)
    artifact = workshop_rigid.compile_rigid(design)
    package = workshop_rigid.package(artifact,drop_height_m=config.get("drop_height_m",.2),
                                    horizontal_speed_m_s=config.get("horizontal_speed_m_s",0))
    steps = max(1,round(duration/package["fixed_dt_s"]))
    engine = _engine(app)
    with tempfile.TemporaryDirectory(prefix="banjo-rigid-trial-") as folder:
        source = Path(folder)/"source.json"
        source.write_text(json.dumps(package,allow_nan=False),encoding="utf-8")
        try:
            completed = subprocess.run([str(engine),"--trace",str(source),str(steps)],
                                       capture_output=True,text=True,timeout=20,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise ValueError("Native rigid trial failed; no result certified: " + str(exc)) from exc
        if len(completed.stdout)>32*1024*1024:
            raise ValueError("Native rigid trace exceeded its response budget; no result certified")
        try:
            result = json.loads(completed.stdout)
        except (ValueError,TypeError) as exc:
            raise ValueError("Native rigid trial returned no valid evidence") from exc
        if completed.returncode or not isinstance(result,dict) or result.get("error"):
            detail=result.get("error") if isinstance(result,dict) else "invalid native reply"
            raise ValueError("Native rigid trial refused: " + str(detail or completed.stderr[-500:]))
    frames = _verify(artifact,package,result)
    elapsed = steps*package["fixed_dt_s"]
    if not isclose(result.get("elapsed_s",-1),elapsed,abs_tol=1e-9) or not isclose(frames[-1].get("t_s",-1),elapsed,abs_tol=1e-9):
        raise ValueError("Native rigid trial did not complete the requested interval")
    initial_com = package["objects"][0]["position_m"]
    objects=result.get("objects") or []
    if len(objects)!=1 or objects[0].get("id")!=1:
        raise ValueError("Native rigid body report is incomplete")
    final = objects[0]
    delta=[final["position_m"][a]-initial_com[a] for a in range(3)]
    limitations=list(artifact["limitations"])+list(result.get("limitations") or [])
    answer={"schema":"banjo.workshop-rigid-trial.v1","test":"rigid_motion","status":"measured",
            "engine_backed":True,"native_geometry_verified":True,"strength_certified":False,
            "mechanical_model":"rigid","prototype":artifact,
            "requested":{"duration_s":duration,"drop_height_m":config.get("drop_height_m",.2),
                         "horizontal_speed_m_s":config.get("horizontal_speed_m_s",0)},
            "measured":{"elapsed_s":elapsed,"mass_kg":artifact["mass_kg"],"stored_cells":0,
                        "collision_boxes":artifact["collision_boxes"],"centre_of_mass_delta_m":delta,
                        "displacement_m":sqrt(sum(v*v for v in delta)),
                        "initial_energy_j":result.get("initial_energy_j"),
                        "mechanical_energy_j":result.get("mechanical_energy_j"),
                        "internal_fracture":"not modeled","attachment_failure":"not modeled"},
            "solver":{"backend":"rigid-v1","fixed_dt_s":package["fixed_dt_s"],"steps":steps,
                      "position_bits":result.get("position_bits"),"performance":result.get("performance")},
            "limitations":limitations}
    if keep:
        for frame in frames:
            for body in frame["bodies"]:
                body["name"]=artifact["components"][body["element_id"]]["component"]
                body["revision"]=0
        answer["playback"]={"schema":workshop_recording.RECORDING_SCHEMA,"test":"rigid_motion",
                            "geometry_basis":"verified-precise-rigid-shapes","duration_s":elapsed,
                            "frames":frames,"events":[],"limitations":limitations,
                            "sampling":{"interpolated":False,"thinned":len(frames)<steps+1,
                                        "source_steps":steps,"recorded_frames":len(frames),
                                        "max_gap_s":max(b["t_s"]-a["t_s"] for a,b in zip(frames,frames[1:]))}}
    return answer
