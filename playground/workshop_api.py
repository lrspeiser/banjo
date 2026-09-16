"""The Workshop's server side: one model, read by the page and by the agent.

Every design decision lives in ``mcp/workshop.py``.  This module turns it into
the answers ``/api/workshop/*`` gives, so the page can render candidates without
knowing how a leg is laid out, and a later agent lane (docs/workshop-next.md
stage 4) can call exactly the same operations.

Nothing here opens the engine, steps physics or touches a live room.  The
workshop's whole point is that exploring a candidate costs the world nothing.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
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

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_lock = threading.Lock()

#: What a fresh bench offers for each assembly: the two parameters whose
#: difference a person can actually see, swept into a first set of candidates.
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

#: What "more like this" nudges, per assembly, and by how much.
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
    assembly(kind)  # raises KeyError naming what the workshop does know
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
    """A short name for a candidate, made of what actually varies."""
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
    """Everything the bench can make, and every family it makes it from."""
    return {
        "schema": WORKSHOP_SCHEMA,
        "families": ComponentLibrary().described(),
        "assemblies": assemblies(),
        "seeds": {k: sorted(v) for k, v in SEED_SWEEPS.items()},
    }


def open_workshop(app: Any, body: Any) -> dict[str, Any]:
    """Open a bench against a frozen world revision, with a first set to look at."""
    body = _object(body)
    kind = _kind(body)
    revision = str(body.get("world_revision") or "unopened-world")
    session = WorkshopSession(
        session_id=str(body.get("session_id") or ("bench-%d" % int(time.time() * 1000))),
        world_revision=revision,
        target=str(body.get("target") or kind))
    generation = _generation(body)
    return {
        "schema": WORKSHOP_SCHEMA,
        "session": session.described(),
        **library(),
        "kind": kind,
        "generation": generation,
        "candidates": _spread(kind, _parameters(body),
                              SEED_SWEEPS.get(kind, {}), generation),
    }


def candidates(app: Any, body: Any) -> dict[str, Any]:
    """A fresh set for one assembly: the bench's Reset, and its Object picker."""
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
    """Six candidates around the one that was chosen."""
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
            values["leg_style"] = "splayed" if base["leg_style"] == "straight" else base["leg_style"]
        design = assemble(kind, design_id="%s-g%d-v%d" % (kind, generation, index + 1),
                          parameters=values)
        made.append(_candidate(design, spec))
    return {"schema": WORKSHOP_SCHEMA, "kind": kind, "generation": generation,
            "candidates": made}


def plan(app: Any, body: Any) -> dict[str, Any]:
    """Snap one chosen candidate to the cell grid. Still not committed."""
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
    """Keep one feedback record, so a preference outlives the browser that gave it.

    localStorage made feedback a note on one machine. Evidence about a design
    belongs with the design (docs/workshop-next.md stage 3).
    """
    body = _object(body)
    kind = _kind(body)
    design_id = str(body.get("design_id") or kind)
    if not _SAFE_ID.match(design_id):
        raise ValueError("design_id must be letters, digits, dot, dash or underscore")
    design = assemble(kind, design_id=design_id, parameters=_parameters(body))
    rating = body.get("rating")
    if rating not in (None, "") and int(rating) not in range(1, 6):
        raise ValueError("rating must be 1 through 5")
    record = feedback(design,
                      rating=int(rating) if rating not in (None, "") else None,
                      selected=bool(body.get("selected", True)),
                      note=str(body.get("note", ""))[:2000])
    record["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record["fingerprint"] = materialize(design)["fingerprint"]
    where = _store(app) / "feedback.jsonl"
    with _lock:
        with where.open("a", encoding="utf-8") as out:
            out.write(json.dumps(record, sort_keys=True) + "\n")
        with where.open(encoding="utf-8") as back:
            kept = sum(1 for _ in back)
    return {"schema": WORKSHOP_SCHEMA, "saved": record, "kept": kept}


def remembered(app: Any, body: Any = None) -> dict[str, Any]:
    """Every feedback record this bench has kept, newest first."""
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
    return {"schema": WORKSHOP_SCHEMA, "kept": len(rows), "feedback": rows[:200]}
