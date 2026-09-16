"""Isolated engine trials for selected Workshop candidates.

A trial owns a LiveWorld session of its own. It never borrows ``app.live`` and
never carries, reopens or writes ``app.room``. The outside world can therefore
remain frozen while this module destroys as many prototypes as necessary.

The first trial is deliberately narrow: a vertical static-load setup for a
single-material fused assembly (table/chair/stool/bench style). It reports what
the engine measured but does not invent an acceptance tolerance; a caller may
compare evidence only against criteria the design actually declares.
"""
from __future__ import annotations

from math import acos, isfinite
from pathlib import Path
from typing import Any, Callable

import fracture_lab
import live_session
from mcp import engine_materials
from mcp.workshop import WorkshopDesign

TRIAL_SCHEMA = "banjo.workshop-trial.v1"
DEFAULT_CELL_M = 0.04
DEFAULT_DURATION_S = 2.0
_LOAD_MATERIAL = "iron"


def _box_body(name: str, part, *, shift_y: float, join: str) -> dict[str, Any]:
    material = engine_materials.canonical(part.material)
    if not engine_materials.known(material):
        raise ValueError(
            f"{part.material!r} has no Banjo engine material preset; the prototype cannot be run")
    # fracture_lab.validate consumes the authored scene spelling (millimetres),
    # then normalizes it for the live runner. Passing its post-normalization
    # dimensions_m/center_m spelling here made every scratch trial invalid.
    return {
        "name": name,
        "shape": "box",
        "material": material,
        "size_mm": [1000.0 * float(v) for v in part.size_m],
        "center_mm": [1000.0 * float(part.center_m[0]),
                      1000.0 * (float(part.center_m[1]) + shift_y),
                      1000.0 * float(part.center_m[2])],
        "velocity_m_s": [0.0, 0.0, 0.0],
        "anchored": False,
        "join": join,
        "rotation_deg": [float(v) for v in part.rotation_deg],
    }


def _target_part(design: WorkshopDesign, on: str):
    part = next((p for p in design.parts if p.name == on), None)
    if part is None:
        part = next((p for p in design.parts if p.role == on), None)
    if part is None and on == "top":
        part = next((p for p in design.parts if p.name in {"top", "seat", "deck"}), None)
    if part is None:
        raise ValueError(f"the static load names {on!r}, but no such part/role exists")
    return part


def prototype_scene(design: WorkshopDesign, *, load_kg: float,
                    on: str = "top", cell_size_m: float = DEFAULT_CELL_M) -> dict[str, Any]:
    """Candidate + one weight, in a local scratch scene."""
    design.validate()
    load_kg = float(load_kg)
    cell = float(cell_size_m)
    if not isfinite(load_kg) or load_kg <= 0:
        raise ValueError("load_kg must be a finite positive number")
    if not isfinite(cell) or not 0.005 <= cell <= 0.1:
        raise ValueError("scratch trial cell_size_m must be 5 to 100 mm")

    materials = {engine_materials.canonical(p.material) for p in design.parts}
    unsupported = sorted(m for m in materials if not engine_materials.known(m))
    if unsupported:
        raise ValueError("the engine has no Banjo engine material preset for " + ", ".join(unsupported))
    if len(materials) != 1:
        raise ValueError(
            "the first fused Workshop prototype supports one material only; a join group "
            "takes the first body's material, so a mixed-material trial would lie")

    lowest = min(c[1] for part in design.parts for c in part.corners_m())
    shift_y = -lowest + 0.002
    join = "workshop-prototype"
    bodies = [_box_body(f"candidate/{p.name}", p, shift_y=shift_y, join=join)
              for p in design.parts]
    approximated = [p.name for p in design.parts if p.shape != "box"]

    target = _target_part(design, on)
    highest = max(c[1] for c in target.corners_m()) + shift_y
    side = (load_kg / engine_materials.density(_LOAD_MATERIAL)) ** (1.0 / 3.0)
    if side < 2 * cell:
        raise ValueError(
            f"{load_kg:g} kg of {_LOAD_MATERIAL} is only {side * 1000:.1f} mm across at "
            f"a {cell * 1000:.0f} mm cell; use a finer trial cell or a larger load")
    load_name = "workshop/test-load"
    bodies.append({
        "name": load_name,
        "shape": "box",
        "material": _LOAD_MATERIAL,
        "size_mm": [side * 1000.0, side * 1000.0, side * 1000.0],
        "center_mm": [float(target.center_m[0]) * 1000.0,
                      (highest + side / 2 + 0.002) * 1000.0,
                      float(target.center_m[2]) * 1000.0],
        "velocity_m_s": [0.0, 0.0, 0.0],
        "anchored": False,
        "rotation_deg": [0.0, 0.0, 0.0],
    })
    spec = fracture_lab.validate({
        "algorithm": "lattice",
        "cell_m": cell,
        "plasticity": "on",
        "bodies": bodies,
    })
    return {
        "spec": spec,
        "root_body": bodies[0]["name"],
        "load_body": load_name,
        "load_kg": load_kg,
        "load_on": on,
        "approximated_parts": approximated,
        "shift_y_m": shift_y,
        "cell_size_m": cell,
    }


def _body(state: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((b for b in state.get("bodies") or [] if b.get("name") == name), None)


def _quat_angle_deg(a: list[float], b: list[float]) -> float:
    dot = abs(sum(float(x) * float(y) for x, y in zip(a, b)))
    dot = max(-1.0, min(1.0, dot))
    return 2.0 * acos(dot) * 180.0 / 3.141592653589793


def _run_to(session: Any, target_s: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = session.send(op="poses")
    fractures: list[dict[str, Any]] = []
    guard = 0
    while float(state.get("t", 0.0)) < target_s - 1e-12:
        guard += 1
        if guard > 100000:
            raise RuntimeError(f"scratch trial stopped advancing at t={state.get('t')}")
        state = session.send(op="step", dt=1 / 120.0, n=1)
        while state.get("breakable"):
            name = str(state["breakable"][0])
            state = session.send(op="fracture", name=name, window_s=0.003)
            fractures.append({"name": name, "at_s": round(float(state.get("t", 0.0)), 6)})
    return state, fractures


def run_static_load(app: Any, design: WorkshopDesign, *, load_kg: float,
                    on: str = "top", cell_size_m: float = DEFAULT_CELL_M,
                    duration_s: float = DEFAULT_DURATION_S,
                    session_factory: Callable[..., Any] = live_session.Session) -> dict[str, Any]:
    """Run one isolated load test and return measurements, never a world edit."""
    duration = float(duration_s)
    if not isfinite(duration) or not 0.1 <= duration <= 10.0:
        raise ValueError("duration_s must be between 0.1 and 10 seconds")
    setup = prototype_scene(design, load_kg=load_kg, on=on, cell_size_m=cell_size_m)
    engine = Path(getattr(app, "engine_path"))
    runs = Path(getattr(app, "runs_path")) / "workshop-trials"
    runs.mkdir(parents=True, exist_ok=True)
    session = session_factory(engine, setup["spec"], runs)
    try:
        initial = session.send(op="poses")
        final, fractures = _run_to(session, duration)
    finally:
        session.close()

    a = _body(initial, setup["root_body"])
    b = _body(final, setup["root_body"])
    load = _body(final, setup["load_body"])
    moved = None
    turned = None
    if a is not None and b is not None:
        pa, pb = a.get("position_m") or [0, 0, 0], b.get("position_m") or [0, 0, 0]
        moved = ((float(pb[0]) - float(pa[0])) ** 2
                 + (float(pb[1]) - float(pa[1])) ** 2
                 + (float(pb[2]) - float(pa[2])) ** 2) ** 0.5
        qa = a.get("orientation_wxyz") or [1, 0, 0, 0]
        qb = b.get("orientation_wxyz") or [1, 0, 0, 0]
        turned = _quat_angle_deg(qa, qb)

    return {
        "schema": TRIAL_SCHEMA,
        "evidence": "engine-trial",
        "trial": "static_load",
        "design_id": design.design_id,
        "requested": {"load_kg": round(float(load_kg), 4), "on": on,
                      "duration_s": duration, "cell_size_m": float(cell_size_m)},
        "prototype": {
            "root_body": setup["root_body"],
            "approximated_parts": setup["approximated_parts"],
            "body_count": len(setup["spec"].get("bodies") or []),
            "one_material_join": True,
        },
        "measured": {
            "clock_s": round(float(final.get("t", 0.0)), 6),
            "prototype_present": b is not None,
            "load_present": load is not None,
            "prototype_displacement_m": round(moved, 6) if moved is not None else None,
            "prototype_rotation_change_deg": round(turned, 4) if turned is not None else None,
            "load_position_m": ([round(float(v), 6) for v in load.get("position_m", [])]
                                if load is not None else None),
            "fractures": fractures,
        },
        "acceptance": {
            "status": "not-declared",
            "why": ("the assembly declares the load to try, but not a displacement/rotation/failure "
                    "tolerance; this result is evidence, not an invented pass/fail"),
        },
        "limitations": (["non-box Workshop parts use their occupied box in this first gross-load trial"]
                        if setup["approximated_parts"] else []),
    }


def run_declared_static_load(app: Any, design: WorkshopDesign, **options: Any) -> dict[str, Any]:
    trial = next((t for t in design.tests if t.get("kind") == "static_load"), None)
    if trial is None:
        raise ValueError("this design declares no static_load trial")
    return run_static_load(app, design, load_kg=float(trial.get("load_kg", 0)),
                           on=str(trial.get("on") or "top"), **options)
