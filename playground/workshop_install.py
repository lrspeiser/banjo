"""Explicit Workshop -> live world prototype placement.

This first adapter installs a single-material, monolithic solid into a flat-floor
room in authoring mode. It does NOT manufacture from inventory, certify strength,
or collapse articulated machines into solids. Preview runs a scratch native
carry/geometry check; commit repeats it against an unchanged source snapshot,
persists the complete new room, then swaps the live session. No old-world reset
or snapshot fallback is permitted. All state comparisons fail closed.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import hashlib
import json
import logging
import math
import re
import struct
import time
from types import SimpleNamespace
from typing import Any
import uuid

import fracture_lab
import live_session
import world_access
import world_room
import precise_rigid
import workshop_sparse_trial as sparse
from mcp import engine_materials, workshop_components, workshop_visual, workshop_matter_metrics, workshop_rigid

SCHEMA = "banjo.workshop-install.v1"
MAX_PREVIEWS = 8
PREVIEW_TTL_S = 300
MAX_RECEIPTS = 64
MAX_CELLS = 16000
_FIXED_ROLES = {"leg", "post", "beam", "brace", "apron", "stretcher", "top", "panel", "surface"}
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
log = logging.getLogger("banjo")


def _object(body: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError("Invalid installation request fields")
    return body


def _token(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(f"{name} must be an 8-80 character identifier")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _inventory(room: Any) -> Any:
    current = getattr(room, "inventory", None)
    value = current.record() if callable(getattr(current, "record", None)) else getattr(room, "inventory_record", None)
    return deepcopy(value)


@contextmanager
def _world(app: Any):
    # The HTTP gate also excludes room/spec/inventory changes. The native locks
    # cover direct in-process callers that do not pass through HTTP.
    with world_access.gate(app).enter(exclusive=True):
        if getattr(app, "live_holder", None) != "world" or getattr(app, "room", None) is None:
            raise ValueError("Open a world first; Workshop cannot silently open or replace a room")
        live = app.live
        inventory_lock = getattr(getattr(app.room, "inventory", None), "lock", None)
        with (inventory_lock if inventory_lock is not None else nullcontext()), live._lock:
            old = live.session
            if old is None:
                raise ValueError("Open a world first")
            if not isinstance(old, live_session.Session) or getattr(app, "live_inprocess", False):
                raise ValueError("Installation requires the native subprocess carry adapter; this lane cannot preserve a changed world")
            with old._lock:
                yield app.room, live, old


def _source(room: Any, old: Any, body: dict[str, Any]) -> None:
    if body.get("session") != old.id or body.get("scene") != room.scene:
        raise ValueError("The source world changed. Refresh the placement context and preview again")
    if old.spec_digest != live_session.spec_digest(room.spec):
        raise ValueError("The room has unpublished edits; reopen it before placing a prototype")


def _snapshot(live: Any) -> dict[str, Any]:
    saved, why = live.snapshot()
    if saved is None:
        raise ValueError(f"Installation needs a current complete snapshot: {why}. The old world is unchanged")
    readiness = saved.get("carry_readiness")
    if not isinstance(readiness, dict) or readiness.get("schema") != "banjo.carry-readiness.v1":
        raise ValueError("Rebuild the native engine: this binary cannot check complete carry readiness")
    if readiness.get("pending_heaters") != 0 or readiness.get("gas_regions") != 0:
        raise ValueError("Installation cannot preserve pending heaters or live gas regions; let the heater finish or use a supported room")
    return saved


def _supported(room: Any, old: Any) -> None:
    if room.spec.get("terrain") or room.spec.get("water"):
        raise ValueError("This prototype adapter supports flat-floor rooms only; terrain/water placement is not implemented. Use the yard")
    if (room.spec.get("thermo") or {}).get("gas_regions") or (room.spec.get("thermo") or {}).get("heaters"):
        raise ValueError("Installation cannot yet carry declared gas regions or timed heaters without resetting them")
    if room.scene not in world_room.SCENES:
        raise ValueError("Installation needs a persistently saved room")
    if not isinstance(getattr(old, "declared", None), dict):
        raise ValueError("The current session has no carry declaration")


def context(app: Any, body: Any) -> dict[str, Any]:
    _object(body, set())
    with _world(app) as (room, live, old):
        return {"schema": SCHEMA, "scene": room.scene, "session": old.id,
                "cell_size_m": float(old.spec["cell_m"]), "mode": "authoring",
                "limits": "Single-material monolithic prototypes, flat floor; no inventory or fabrication-energy charge; not strength certified."}


def _bounds(cells, h):
    return ([min(g[a] for g in cells)*h for a in range(3)],
            [(max(g[a] for g in cells)+1)*h for a in range(3)])


def _body_bounds(body: dict[str, Any], h: float):
    """Conservative actual-cell AABB, including rotated cubic cell extents."""
    if body.get("mechanical_model") == precise_rigid.MODEL:
        return precise_rigid.bounds(body["precise_rigid_definition"]["parts"], body["pose"]["com_m"], body["pose"]["q_wxyz"])
    raw = base64.b64decode(body["offsets_b64"], validate=True)
    if not raw or len(raw) % 24:
        raise ValueError("An existing body lacks exact collision geometry")
    w, x, y, z = body["pose"]["q_wxyz"]
    r = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
         (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
         (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    com = body["pose"]["com_m"]
    extent = [sum(abs(v) for v in row)*h/2 for row in r]
    lo, hi = [math.inf]*3, [-math.inf]*3
    for p in struct.iter_unpack("<ddd", raw):
        for a in range(3):
            v = com[a] + sum(r[a][b]*p[b] for b in range(3))
            if not math.isfinite(v):
                raise ValueError("Nonfinite existing collision geometry")
            lo[a] = min(lo[a], v-extent[a]); hi[a] = max(hi[a], v+extent[a])
    # Some rigid collision shapes extend beyond sampled cell centres. Include
    # their declared envelope too; false-positive refusals are preferable to
    # admitting a penetrating placement.
    dimensions = body.get("dimensions_m") or []
    if len(dimensions) != 3 or any(not math.isfinite(v) or v <= 0 for v in dimensions):
        raise ValueError("An existing body lacks a valid collision envelope")
    for a in range(3):
        half = sum(abs(r[a][b])*dimensions[b]/2 for b in range(3))
        lo[a] = min(lo[a], com[a]-half); hi[a] = max(hi[a], com[a]+half)
    return lo, hi


def _clearance(snapshot, cells, h):
    lo, hi = _bounds(cells, h)
    conflicts = []
    for body in snapshot["bodies"]:
        if body.get("parked"):
            continue
        blo, bhi = _body_bounds(body, h)
        # A positive gap on ANY axis is necessary. Touching is refused too:
        # support on another object and custom joint mating are a later adapter.
        if all(lo[a] <= bhi[a]+1e-8 and blo[a] <= hi[a]+1e-8 for a in range(3)):
            conflicts.append(str(body["name"]))
    if conflicts:
        raise ValueError("Placement overlaps or touches existing objects (conservative bounds): " + ", ".join(conflicts[:8]))


def _joint_readouts_match(before: list, after: list) -> bool:
    if len(before) != len(after):
        return False
    def float_code(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Nonfinite joint angle")
        bits = struct.unpack("<I", struct.pack("<f", value))[0]
        return (0x80000000-(bits & 0x7fffffff)) if bits & 0x80000000 else bits+0x80000000
    for a, b in zip(before, after):
        a, b = deepcopy(a), deepcopy(b)
        ah, bh = a.get("held"), b.get("held")
        if isinstance(ah, dict) and isinstance(bh, dict) and "at" in ah and "at" in bh:
            # Jolt recomputes this diagnostic from the SAME restored poses in
            # single precision. One measured case differs by one float32 ULP.
            # Bound only that derived angle; limits, anchors, reference frames,
            # motor state and every other serialized field remain exact.
            x, y = ah.pop("at"), bh.pop("at")
            if abs(float_code(x)-float_code(y)) > 4:
                return False
        if a != b:
            return False
    return True


def _preserved(before: dict[str, Any], after: dict[str, Any], root: str) -> None:
    """Append-only carry must keep the serialized physical state, not just poses.

    Exact body and part equality also establishes unchanged node/bond index
    ranges before comparing damage/plastic arrays. Unknown future global state
    is compared, not ignored. New heat lumps may be appended by the compiler;
    every original lump and the rest of the heat network must remain identical.
    """
    current = {b["name"]: b for b in after["bodies"]}
    prior = {b["name"]: b for b in before["bodies"]}
    if len(current) != len(after["bodies"]) or set(current) != set(prior) | {root}:
        raise ValueError("Staging did not preserve the exact existing body set")
    for name, body in prior.items():
        if body != current[name]:
            raise ValueError(f"Staging changed existing physical state for {name}; installation refused")
    parts = {tuple(p["bodies"]): p for p in after["parts"]}
    for part in before["parts"]:
        if parts.get(tuple(part["bodies"])) != part:
            raise ValueError("Staging changed existing topology or material declarations")
    exceptions = {"bodies", "parts", "fingerprint", "spec_digest", "next", "heat", "joints"}
    if not _joint_readouts_match(before.get("joints", []), after.get("joints", [])):
        raise ValueError("Staging changed existing joints; installation refused")
    for key in set(before) | set(after):
        if key not in exceptions and before.get(key) != after.get(key):
            raise ValueError(f"Staging changed existing {key}; installation refused")
    bnext, anext = before.get("next", {}), after.get("next", {})
    if set(bnext) != set(anext) or any(anext[k] != v+(1 if k=="body" else 0) for k,v in bnext.items()):
        raise ValueError("Staging changed unrelated native identifiers")
    bh, ah = before.get("heat"), after.get("heat")
    if bh is not None:
        if not isinstance(ah, dict):
            raise ValueError("Staging lost thermal state")
        for key, value in bh.items():
            if key == "lumps":
                # Native heat lump dictionaries retain body ownership. Do not
                # assume their ordering is stable when new matter is appended.
                if any(lump not in ah.get("lumps", []) for lump in value):
                    raise ValueError("Staging changed an existing heat lump")
            elif ah.get(key) != value:
                raise ValueError(f"Staging changed thermal {key}")


def _stage(app, live, old, spec, snapshot, matter, root, shift):
    staging = live_session.Live()
    scratch = SimpleNamespace(engine_path=app.engine_path, runs_path=app.runs_path,
                              live_inprocess=False, on_live_reply=None)
    try:
        opened = staging.open(scratch, {"spec": deepcopy(spec), "snapshot": snapshot, "carry": True}, carry_from=old)
        restored = opened.get("restored") or {}
        if restored.get("tier") != "carried" or restored.get("not_carried"):
            raise ValueError("The native engine could not carry the original world unchanged")
        if any(opened.get(k) for k in ("joint_problems", "machine_problems", "blade_problems", "tool_point_problems")):
            raise ValueError("Staging could not restore every existing joint, control or tool")
        saved = _snapshot(staging)
        _preserved(snapshot, saved, root)
        if matter.get("schema") == workshop_rigid.SCHEMA:
            precise_rigid.verify(saved, matter, root)
        else:
            sparse.verify_engine_matter(saved, matter, root, placement_grid=shift)
        return staging, saved
    except BaseException:
        if staging.session:
            staging.session.close()
        raise


def _preview_cache(app):
    cache = getattr(app, "_workshop_install_previews", None)
    if cache is None:
        cache = app._workshop_install_previews = {}
    now = time.monotonic()
    for key in list(cache):
        if cache[key]["expires"] <= now:
            del cache[key]
    return cache


def preview(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body, {"session", "scene", "mode", "candidate", "position_m"})
    if body.get("mode") != "authoring":
        raise ValueError("Choose authoring mode explicitly. Inventory-funded fabrication is not implemented; no resources have been charged")
    pos = body.get("position_m")
    if not isinstance(pos, list) or len(pos) != 2 or any(type(x) not in (float,int) or not math.isfinite(x) or abs(x)>100 for x in pos):
        raise ValueError("position_m must be finite [x,z] coordinates within 100 metres")
    with _world(app) as (room, live, old):
        _source(room, old, body); _supported(room, old)
        if getattr(app, "store", None) is None:
            raise ValueError("Installation requires a persistent room store")
        design, overrides = workshop_components.design_from_spec(body.get("candidate") or {})
        models = workshop_rigid.requested_models(design, overrides)
        if models == {"rigid"}:
            return _preview_rigid(app, room, live, old, design, overrides, pos)
        workshop_rigid.require_lattice(design, "Live-room prototype installation")
        if any(p.role not in _FIXED_ROLES for p in design.parts):
            raise ValueError("Only fixed structural solids can be placed by this adapter; articulated machines and containers need their own interfaces")
        h = float(old.spec["cell_m"])
        matter = workshop_visual.matter_document(design, overrides, cell_size_m=h, exterior_only=False)
        cells = sparse._grid_set(matter)
        if not cells or len(cells)>MAX_CELLS:
            raise ValueError("The prototype exceeds the native room's cell budget")
        measured = workshop_matter_metrics.measure(matter, expected_components=[p.name for p in design.parts])
        if not measured["measured"]["geometry_coherent"]:
            raise ValueError("The prototype has disconnected or missing physical components; repair it before installation")
        materials = {engine_materials.canonical(c["material"]) for c in matter["cells"]}
        if len(materials) != 1:
            raise ValueError("Mixed-material installation requires explicit interfaces; it cannot be fused into one material")
        shift = (round(pos[0]/h), -min(g[1] for g in cells), round(pos[1]/h))
        placed = {tuple(g[a]+shift[a] for a in range(3)) for g in cells}
        boxes = sparse.decompose_cells(placed)
        if len(boxes)>sparse.MAX_SCENE_BOXES or sparse.cells_from_boxes(boxes)!=placed:
            raise ValueError("Prototype geometry cannot be represented exactly within the native scene limit")
        root = "workshop-" + uuid.uuid4().hex[:16]
        added = [sparse._box_body(root if i==0 else f"{root}-{i}", box, h, next(iter(materials)), root)
                 for i,box in enumerate(boxes)]
        saved = _snapshot(live)
        _clearance(saved, placed, h)
        spec = deepcopy(room.spec)
        spec["bodies"] = spec["bodies"] + added
        fracture_lab.validate(spec)  # admission only; never rewrite the old declarations
        staged, _ = _stage(app, live, old, spec, saved, matter, root, shift)
        staged.session.close()
        token = uuid.uuid4().hex
        answer = {"schema": SCHEMA, "status": "preview", "preview_id": token,
                  "scene": room.scene, "session": old.id, "mode": "authoring",
                  "root_body": root, "design_id": design.design_id,
                  "matter_physics_hash": matter["physics_hash"], "cell_size_m": h,
                  "cells": len(cells), "mass_kg": measured["measured"]["mass_kg"],
                  "materials": measured["materials"], "requested_position_m": pos,
                  "placement_grid": list(shift), "applied_translation_m": [s*h for s in shift],
                  "bounds_m": _bounds(placed,h), "engine_grid_verified": True,
                  "existing_state_preserved": True, "resources_charged": False,
                  "strength_certified": False, "expires_in_s": PREVIEW_TTL_S,
                  "limits": "Monolithic authoring prototype; not inventory-funded fabrication. Exact geometry is not proof of strength. Contact warm-start memory is not carried. Derived hinge-angle readouts may differ by at most four float32 ULP; all other compared state is exact."}
        cache = _preview_cache(app)
        while len(cache)>=MAX_PREVIEWS:
            del cache[next(iter(cache))]
        cache[token] = {"expires": time.monotonic()+PREVIEW_TTL_S, "answer": deepcopy(answer),
                        "source_hash": _hash([saved,room.spec,_inventory(room)]),
                        "spec": spec, "matter": matter, "root": root, "shift": shift}
        return answer



def _preview_rigid(app, room, live, old, design, overrides, pos):
    artifact = workshop_rigid.compile_rigid(design, overrides)
    saved = _snapshot(live)
    if saved.get("carry_readiness", {}).get("precise_rigid_version") != 1:
        raise ValueError("Rebuild the native live engine for precise rigid installation; this binary does not declare support")
    root = "workshop-" + uuid.uuid4().hex[:16]
    body, translation = precise_rigid.placement(artifact, root, pos)
    spec = deepcopy(room.spec)
    spec["precise_rigid_bodies"] = spec.get("precise_rigid_bodies", []) + [body]
    # Admission before any new process; this does not rewrite old declarations.
    normalised = precise_rigid.normalise(spec["precise_rigid_bodies"], spec)
    body = normalised[-1]
    spec["precise_rigid_bodies"][-1] = body
    artifact["live_definition"] = body
    bounds = precise_rigid.bounds(body["parts"], body["position_m"], body["orientation_wxyz"])
    for existing in saved["bodies"]:
        if "parked" in existing:
            continue
        lo, hi = _body_bounds(existing, float(old.spec["cell_m"]))
        if all(bounds[0][a] < hi[a]+.001 and bounds[1][a] > lo[a]-.001 for a in range(3)):
            raise ValueError("Prototype placement overlaps the current collision envelope of " + existing["name"])
    fracture_lab.validate(spec)
    staged, _ = _stage(app, live, old, spec, saved, artifact, root, None)
    staged.session.close()
    token = uuid.uuid4().hex
    answer = {"schema": SCHEMA, "status": "preview", "preview_id": token,
              "scene": room.scene, "session": old.id, "mode": "authoring", "root_body": root,
              "design_id": design.design_id, "matter_physics_hash": artifact["physics_hash"],
              "mechanical_model": precise_rigid.MODEL, "cell_size_m": float(old.spec["cell_m"]),
              "cells": 0, "collision_boxes": artifact["collision_boxes"], "mass_kg": artifact["mass_kg"],
              "materials": [artifact["material"]], "requested_position_m": pos,
              "placement_grid": None, "applied_translation_m": translation, "bounds_m": bounds,
              "engine_grid_verified": False, "native_precise_geometry_verified": True,
              "existing_state_preserved": True, "resources_charged": False, "strength_certified": False,
              "expires_in_s": PREVIEW_TTL_S, "limits": precise_rigid.LIMITS +
              " Geometry, mass and state carry were checked; contact warm-start memory is not persisted."}
    cache = _preview_cache(app)
    while len(cache) >= MAX_PREVIEWS:
        del cache[next(iter(cache))]
    cache[token] = {"expires": time.monotonic()+PREVIEW_TTL_S, "answer": deepcopy(answer),
                    "source_hash": _hash([saved, room.spec, _inventory(room)]),
                    "spec": spec, "matter": artifact, "root": root, "shift": None}
    return answer

def commit(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body, {"session", "scene", "preview_id", "request_id"})
    token = _token(body.get("preview_id"), "preview_id")
    request = _token(body.get("request_id"), "request_id")
    with _world(app) as (room, live, old):
        if body.get("scene") != room.scene:
            raise ValueError("The source room changed")
        receipts = getattr(room, "workshop_installs", [])
        for receipt in receipts:
            if receipt.get("request_id") == request:
                if receipt.get("preview_id") != token:
                    raise ValueError("This request_id was already used for a different installation")
                return {**deepcopy(receipt), "replayed": True}
        _source(room, old, body); _supported(room, old)
        plan = _preview_cache(app).get(token)
        if plan is None:
            raise ValueError("The preview expired or is no longer available. Preview again")
        if plan["answer"]["session"] != old.id or plan["answer"]["scene"] != room.scene:
            raise ValueError("The preview belongs to a different world session")
        before = _snapshot(live)
        if plan["source_hash"] != _hash([before,room.spec,_inventory(room)]):
            raise ValueError("The world or inventory changed after preview. Preview again; nothing was installed")
        staged, saved = _stage(app, live, old, plan["spec"], before, plan["matter"], plan["root"], plan["shift"])
        try:
            receipt = {**deepcopy(plan["answer"]), "status": "installed", "request_id": request,
                       "session": staged.session.id, "source_session": old.id, "replayed": False}
            receipt.pop("expires_in_s", None)
            kept = deepcopy(receipts[-(MAX_RECEIPTS-1):]) + [deepcopy(receipt)]
            record = SimpleNamespace(scene=room.scene, spec=plan["spec"], chat=deepcopy(room.chat),
                                     inventory_record=_inventory(room), world_record=saved, workshop_installs=kept)
            # The only fallible persistent write occurs BEFORE the live swap.
            # A failed atomic save leaves the original process and room intact.
            if not app.store.save(record):
                raise ValueError("The room store refused the installation")
        except BaseException:
            staged.session.close()
            raise
        room.spec = plan["spec"]
        room.world_record = saved
        room.workshop_installs = kept
        live.session = staged.session
        staged.session = None
        live.session.on_reply = getattr(app, "on_live_reply", None)
        _preview_cache(app).clear()
        # Failure to clean up the retired subprocess cannot turn a successful
        # persisted commit into a reported failure and encourage a duplicate.
        try:
            old.close()
        except Exception:
            log.exception("Retired Workshop source session did not close cleanly")
        return receipt
