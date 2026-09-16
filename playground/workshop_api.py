"""The Workshop's server side: one model, read by the page and by the agent.

Every design decision lives in ``mcp/workshop.py``. This module turns it into
the answers ``/api/workshop/*`` gives, so the page can render candidates without
knowing how a leg is laid out, and an agent lane can call exactly the same
operations.

Nothing here opens the engine, steps physics or mutates a live room. Exploration
is pure computation. Saved designs and feedback are durable Workshop records,
not world edits.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.workshop import (  # noqa: E402
    WORKSHOP_SCHEMA,
    ComponentLibrary,
    WorkshopSession,
    assemble,
    assemblies,
    assembly,
    feedback,
    materialize,
    variants,
)
from mcp.workshop_statics import declared_statics  # noqa: E402
import workshop_store  # noqa: E402

_lock = threading.Lock()

SEED_SWEEPS: dict[str, dict[str, list[Any]]] = {
    "table": {"leg_style": ["straight", "splayed", "tapered"],
              "leg_section_m": [0.045, 0.065]},
    "stool": {"leg_style": ["straight", "splayed", "tapered"],
              "leg_section_m": [0.032, 0.045]},
    "bench": {"leg_style": ["straight", "splayed", "tapered"],
              "leg_section_m": [0.04, 0.06]},
    "chair": {"leg_style": ["straight", "splayed", "tapered"],
              "back_height_m": [0.38, 0.5]},
    "shelf-unit": {"shelves": [3, 4, 5], "side_thickness_m": [0.015, 0.025]},
    "cart": {"wheel_diameter_m": [0.22, 0.32, 0.42], "deck_height_m": [0.3, 0.42]},
}

NUDGES: dict[str, list[tuple[str, list[float]]]] = {
    "table": [("leg_section_m", [-0.015, -0.007, 0.0, 0.007, 0.015, 0.025]),
              ("splay_deg", [0.0, 3.0, 6.0, 9.0, 12.0, 15.0])],
    "stool": [("leg_section_m", [-0.01, -0.005, 0.0, 0.005, 0.01, 0.016]),
              ("splay_deg", [0.0, 4.0, 7.0, 10.0, 13.0, 16.0])],
    "bench": [("leg_section_m", [-0.012, -0.006, 0.0, 0.006, 0.012, 0.02]),
              ("splay_deg", [0.0, 3.0, 6.0, 9.0, 12.0, 15.0])],
    "chair": [("back_height_m", [-0.08, -0.04, 0.0, 0.04, 0.08, 0.14]),
              ("splay_deg", [0.0, 3.0, 6.0, 9.0, 12.0, 15.0])],
    "shelf-unit": [("height_m", [-0.4, -0.2, 0.0, 0.2, 0.4, 0.6]),
                   ("shelves", [0.0, 0.0, 0.0, 1.0, 1.0, 2.0])],
    "cart": [("wheel_diameter_m", [-0.08, -0.04, 0.0, 0.04, 0.08, 0.14]),
             ("deck_height_m", [-0.06, -0.03, 0.0, 0.03, 0.06, 0.1])],
}


def _store(app: Any) -> Path:
    where = Path(getattr(app, "workshop_store", ROOT / "build" / "workshop"))
    where.mkdir(parents=True, exist_ok=True)
    return where


def _object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object")
    return body


def _kind(body: dict[str, Any], fallback: str = "table") -> str:
    kind = body.get("kind", fallback)
    if not isinstance(kind, str):
        raise ValueError("kind must be the name of an assembly")
    assembly(kind)
    return kind


def _parameters(body: dict[str, Any]) -> dict[str, Any]:
    given = body.get("parameters") or {}
    if not isinstance(given, dict):
        raise ValueError("parameters must be a JSON object")
    return given


def _generation(body: dict[str, Any]) -> int:
    try:
        return max(0, min(9999, int(body.get("generation", 0))))
    except (TypeError, ValueError):
        return 0


def _label(kind: str, values: dict[str, Any], spec) -> str:
    known = {p.name for p in spec.parameters}
    bits = []
    if "leg_style" in known:
        bits.append(str(values["leg_style"]))
        bits.append("%d mm legs" % round(values["leg_section_m"] * 1000))
        if values.get("splay_deg"):
            bits.append("%g deg splay" % values["splay_deg"])
    elif kind == "shelf-unit":
        bits.append("%d shelves" % round(values["shelves"]))
        bits.append("%d mm sides" % round(values["side_thickness_m"] * 1000))
    elif kind == "cart":
        bits.append("%d mm wheels" % round(values["wheel_diameter_m"] * 1000))
        bits.append("deck at %.2f m" % values["deck_height_m"])
    return " · ".join(bits) or kind


def _candidate(design, spec) -> dict[str, Any]:
    wire = design.wireframe()
    wire["label"] = _label(design.kind, design.parameters, spec)
    try:
        wire["analytical"] = {"static_loads": declared_statics(design), "limitations": []}
    except ValueError as problem:
        wire["analytical"] = {"static_loads": [], "limitations": [str(problem)]}
    return wire


def _spread(kind: str, base: dict[str, Any], sweeps: dict[str, list[Any]],
            generation: int, purpose: str | None = None) -> list[dict[str, Any]]:
    spec = assembly(kind)
    root = assemble(kind, design_id="%s-g%d" % (kind, generation), purpose=purpose,
                    parameters=base)
    made = variants(root, sweeps) if sweeps else [root]
    out = []
    for index, design in enumerate(made, 1):
        design.design_id = "%s-g%d-v%d" % (kind, generation, index)
        out.append(_candidate(design, spec))
    return out


def library(app: Any = None, body: Any = None) -> dict[str, Any]:
    return {
        "schema": WORKSHOP_SCHEMA,
        "families": ComponentLibrary().described(),
        "assemblies": assemblies(),
        "seeds": {k: sorted(v) for k, v in SEED_SWEEPS.items()},
        "saved_designs": workshop_store.list_saved(_store(app)) if app is not None else [],
    }


def open_workshop(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body)
    generation = _generation(body)
    saved_id = body.get("saved_design_id")
    saved = None
    if saved_id:
        saved, design = workshop_store.load(_store(app), str(saved_id))
        kind = str(saved["kind"])
        spec = assembly(kind)
        candidates_out = [_candidate(design, spec)]
        revision = str(body.get("world_revision") or saved.get("world_revision")
                       or "unopened-world")
        target = str(body.get("target") or saved.get("label") or design.design_id)
    else:
        kind = _kind(body)
        revision = str(body.get("world_revision") or "unopened-world")
        target = str(body.get("target") or kind)
        candidates_out = _spread(kind, _parameters(body),
                                 SEED_SWEEPS.get(kind, {}), generation)

    session = WorkshopSession(
        session_id=str(body.get("session_id") or ("bench-%d" % int(time.time() * 1000))),
        world_revision=revision,
        target=target)
    return {
        "schema": WORKSHOP_SCHEMA,
        "session": session.described(),
        **library(app),
        "kind": kind,
        "generation": generation,
        "candidates": candidates_out,
        **({"saved_design": saved} if saved else {}),
    }


def candidates(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body)
    kind = _kind(body)
    generation = _generation(body)
    sweeps = body.get("sweeps")
    if sweeps is not None and not isinstance(sweeps, dict):
        raise ValueError("sweeps must be a JSON object of parameter to values")
    return {"schema": WORKSHOP_SCHEMA, "kind": kind, "generation": generation,
            "candidates": _spread(kind, _parameters(body),
                                  sweeps if sweeps is not None else SEED_SWEEPS.get(kind, {}),
                                  generation)}


def more_like_this(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body)
    kind = _kind(body)
    spec = assembly(kind)
    base = spec.checked(_parameters(body))
    generation = _generation(body) + 1
    known = {p.name: p for p in spec.parameters}
    made: list[dict[str, Any]] = []
    for index in range(6):
        values = dict(base)
        for name, steps in NUDGES.get(kind, []):
            if name not in known:
                continue
            parameter = known[name]
            moved = float(base[name]) + steps[index] if name != "splay_deg" else steps[index]
            if parameter.low is not None:
                moved = max(parameter.low, moved)
            if parameter.high is not None:
                moved = min(parameter.high, moved)
            values[name] = moved
        if kind in {"table", "stool", "bench", "chair"} and values.get("splay_deg"):
            values["leg_style"] = ("splayed"
                                   if base["leg_style"] == "straight"
                                   else base["leg_style"])
        design = assemble(kind, design_id="%s-g%d-v%d" % (kind, generation, index + 1),
                          parameters=values)
        made.append(_candidate(design, spec))
    return {"schema": WORKSHOP_SCHEMA, "kind": kind, "generation": generation,
            "candidates": made}


def plan(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body)
    kind = _kind(body)
    design = assemble(kind, design_id=str(body.get("design_id") or kind),
                      parameters=_parameters(body))
    try:
        cell = float(body.get("cell_size_m", 0.04))
    except (TypeError, ValueError):
        raise ValueError("cell_size_m must be a number")
    if not 0.002 <= cell <= 0.5:
        raise ValueError("cell_size_m must be between 2 mm and 500 mm")
    return materialize(design, cell_size_m=cell)


def remember(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body)
    kind = _kind(body)
    design_id = workshop_store.safe_design_id(body.get("design_id") or kind)
    design = assemble(kind, design_id=design_id, parameters=_parameters(body))

    rating = body.get("rating")
    if rating not in (None, "") and int(rating) not in range(1, 6):
        raise ValueError("rating must be 1 through 5")
    note = str(body.get("note", ""))[:2000]
    wants_feedback = rating not in (None, "") or bool(note) or "selected" in body

    record = None
    where = _store(app) / "feedback.jsonl"
    if wants_feedback:
        record = feedback(design,
                          rating=int(rating) if rating not in (None, "") else None,
                          selected=bool(body.get("selected", True)),
                          note=note)
        record["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["fingerprint"] = materialize(design)["fingerprint"]
        with _lock:
            with where.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, sort_keys=True) + "\n")

    saved_design = None
    if body.get("save_design"):
        saved_design = workshop_store.save(
            _store(app), design,
            label=str(body.get("label") or design_id),
            parent_design_id=(str(body["parent_design_id"])
                              if body.get("parent_design_id") else None),
            world_revision=(str(body["world_revision"])
                            if body.get("world_revision") else None),
        )

    kept = 0
    if where.exists():
        with _lock:
            with where.open(encoding="utf-8") as back:
                kept = sum(1 for line in back if line.strip())
    designs = workshop_store.list_saved(_store(app))
    return {
        "schema": WORKSHOP_SCHEMA,
        "saved": record,
        "design": saved_design,
        "kept": kept,
        "designs_kept": len(designs),
        "saved_designs": designs,
    }


def remembered(app: Any, body: Any = None) -> dict[str, Any]:
    where = _store(app) / "feedback.jsonl"
    rows: list[dict[str, Any]] = []
    if where.exists():
        with _lock:
            for line in where.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    rows.reverse()
    designs = workshop_store.list_saved(_store(app))
    return {
        "schema": WORKSHOP_SCHEMA,
        "kept": len(rows),
        "feedback": rows[:200],
        "designs_kept": len(designs),
        "saved_designs": designs,
    }
