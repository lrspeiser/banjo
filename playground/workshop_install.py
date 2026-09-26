"""Explicit Workshop -> live world prototype placement.

This first adapter installs a single-material, monolithic solid onto native ground in a saved
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
import workshop_articulation
import workshop_library
from mcp import (engine_materials, joint_efficiency, workshop_components, workshop_machines,
                 workshop_visual, workshop_matter_metrics, workshop_rigid)

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
        heat = saved.get("heat") or {}
        if (readiness.get("thermal_network_version") != 1
                or (heat.get("network") or {}).get("schema") != "banjo.thermal-state.v1"
                or "scene_settings" not in heat):
            raise ValueError("Rebuild the native engine: pending heaters and live gas regions require complete thermal carry")
    return saved


def _supported(room: Any, old: Any) -> None:
    if room.scene not in world_room.SCENES:
        raise ValueError("Installation needs a persistently saved room")
    if not isinstance(getattr(old, "declared", None), dict):
        raise ValueError("The current session has no carry declaration")


def context(app: Any, body: Any) -> dict[str, Any]:
    _object(body, set())
    with _world(app) as (room, live, old):
        return {"schema": SCHEMA, "scene": room.scene, "session": old.id,
                "cell_size_m": float(old.spec["cell_m"]), "mode": "authoring",
                "limits": "Single-material monolithic prototypes on native ground; no inventory or fabrication-energy charge; not strength certified."}


def _bounds(cells, h):
    return ([min(g[a] for g in cells)*h for a in range(3)],
            [(max(g[a] for g in cells)+1)*h for a in range(3)])


def _terrain_state(old):
    if not old.spec.get("terrain"):
        return None
    ground = old.send(op="terrain").get("terrain")
    if not isinstance(ground, dict):
        raise ValueError("Native engine did not return the current terrain")
    # The collision grid, materials and carried excavated stock are physical
    # state too; rendering/view and generation timings are not.
    state = {key: deepcopy(ground[key]) for key in ("grid", "heights_b64", "ground_b64", "carried")}
    ledger = old.send(op="environment").get("environment", {}).get("ground")
    if not isinstance(ledger, dict):
        raise ValueError("Native engine did not return terrain material accounting")
    state["material_accounting"] = deepcopy(ledger)
    return state


def _terrain_floor(old, bounds):
    """Conservative support elevation over the complete horizontal envelope."""
    terrain = _terrain_state(old)
    if terrain is None:
        return 0.0
    grid = terrain["grid"]
    nx, nz, h = grid["nx"], grid["nz"], grid["cell_m"]
    if type(nx) is not int or type(nz) is not int or nx < 2 or nz < 2 or nx*nz > 4_000_000:
        raise ValueError("Unsupported terrain grid")
    if type(h) not in (int,float) or not math.isfinite(h) or h <= 0:
        raise ValueError("Invalid terrain spacing")
    raw = base64.b64decode(terrain["heights_b64"], validate=True)
    if len(raw) != nx*nz*4:
        raise ValueError("Incomplete native terrain heights")
    heights = struct.unpack("<"+"f"*(nx*nz),raw)
    indices = []
    for axis, count, origin in ((0,nx,grid["x0_m"]),(2,nz,grid["z0_m"])):
        lo, hi = (bounds[k][axis]-origin for k in (0,1))
        if lo < 0 or hi > (count-1)*h:
            raise ValueError("The whole product must fit inside the simulated terrain")
        indices.append((max(0,math.floor(lo/h)),min(count-1,math.ceil(hi/h))))
    values = [heights[j*nx+i] for j in range(indices[1][0],indices[1][1]+1)
              for i in range(indices[0][0],indices[0][1]+1)]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Nonfinite terrain height")
    # Covering grid vertices bound the triangle surface even between samples.
    # Add a float32 decoding margin; gravity, not this preview, settles the part.
    return max(values) + max(.001, max(abs(v) for v in values)*2**-22)


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
            # motor state and every other serialized field remain exact. A
            # pin between exact bodies that were moving when the world was
            # saved reads a few hundred ULPs off (measured 1.3e-7 rad on the
            # rover's caster), so a microradian is allowed as well: less than
            # a ten-thousandth of a degree, and a readout, not a declaration.
            x, y = ah.pop("at"), bh.pop("at")
            if abs(float_code(x)-float_code(y)) > 4 and abs(float(x) - float(y)) > 1e-6:
                return False
        if a != b:
            return False
    return True



def _transfers(value):
    transfers = [] if value is None else value if isinstance(value, list) else [value]
    names = [t["body"] for t in transfers]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate thermal output transfer")
    return transfers


def _thermal_preserved(before, after, body_names, thermal_transfer=None):
    """Keep stored state exact; account separately for new network membership.

    Paths and exposed area are geometry-derived, not stored energy. New cold
    parcels entering the heat network cross its boundary even if their rigid
    bodies already existed outside that network.
    """
    if not isinstance(after, dict):
        raise ValueError("Staging lost thermal state")
    old = {l["body"]: l for l in before.get("lumps", [])}
    new = {l["body"]: l for l in after.get("lumps", [])}
    if len(new) != len(after.get("lumps", [])) or not set(new) <= body_names:
        raise ValueError("Staging created invalid thermal ownership")
    complete = ((before.get("network") or {}).get("schema") == "banjo.thermal-state.v1"
                and (after.get("network") or {}).get("schema") == "banjo.thermal-state.v1")
    for name, lump in old.items():
        if name not in new:
            raise ValueError("Staging lost an existing heat lump")
        a, b = deepcopy(lump), deepcopy(new[name])
        if complete:
            # Contact changes the area open to ambient air without changing
            # matter, stored energy, temperature history or damage.
            a.pop("exposed_area_m2", None)
            b.pop("exposed_area_m2", None)
        if a != b:
            raise ValueError("Staging changed an existing heat lump")
    for key in set(before) | set(after):
        if key not in ("lumps", "network") and before.get(key) != after.get(key):
            raise ValueError(f"Staging changed thermal {key}")
    if not complete:
        if before.get("network") != after.get("network"):
            raise ValueError("Staging changed thermal network")
        return

    bn, an = before["network"], after["network"]
    derived = {"contacts", "sights", "sky_fraction", "floor_conductance_w_k"}
    for key in set(bn) | set(an):
        if key not in derived | {"ledger"} and bn.get(key) != an.get(key):
            raise ValueError(f"Staging changed thermal network {key}")

    def vector(encoded):
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) % 8:
            raise ValueError("Invalid thermal numeric array")
        values = [v[0] for v in struct.iter_unpack("<d", raw)]
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("Invalid thermal mass or boundary coefficient")
        return values

    count = len(new)
    for lump in new.values():
        area = lump.get("exposed_area_m2")
        if not isinstance(area, (int, float)) or not math.isfinite(area) or not 0 <= area <= lump["area_m2"]:
            raise ValueError("Invalid exposed thermal surface")
    for field in ("sky_fraction", "floor_conductance_w_k"):
        values = vector(an[field])
        if len(values) != count or (field == "sky_fraction" and any(v > 1 for v in values)):
            raise ValueError("Invalid derived thermal boundary")
    for field in ("contacts", "sights"):
        for path in an[field]:
            if any(type(path.get(k)) is not int or not 0 <= path[k] < count for k in ("a", "b")):
                raise ValueError("Invalid derived thermal path")
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                   for k, v in path.items() if k not in ("a", "b")):
                raise ValueError("Invalid derived thermal coefficient")
    transfers = _transfers(thermal_transfer)
    transferred = {t["body"] for t in transfers}
    energy, mass = [], []
    for name in set(new)-set(old):
        lump = new[name]
        if lump.get("declared") and name not in transferred:
            raise ValueError("New declared thermal inventory needs an explicit transfer")
        for zone in ("surface", "core"):
            parcel = lump[zone]
            kg = vector(parcel["kg_b64"])
            if len(kg) != before["substances"]:
                raise ValueError("New thermal parcel has incompatible substances")
            value = parcel["internal_energy_j"]
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("New thermal parcel has invalid energy")
            mass.extend(kg)
            energy.append(value)
    deltas = {"joined_j": math.fsum(energy), "joined_kg": math.fsum(mass)}
    for transfer in transfers:
        if transfer["body"] in old or transfer["body"] not in new:
            raise ValueError("Thermal output must belong to the newly installed body")
        lump = new[transfer["body"]]
        actual_mass = math.fsum(v for zone in ("surface", "core") for v in vector(lump[zone]["kg_b64"]))
        actual_energy = math.fsum(lump[zone]["internal_energy_j"] for zone in ("surface", "core"))
        for field, actual in (("mass_kg", actual_mass), ("internal_energy_j", actual_energy)):
            if transfer.get(field) != actual:
                raise ValueError("Thermal transfer receipt differs from native output")
        for suffix in ("j", "kg"):
            replaced = transfer["replaced_" + suffix]
            if not math.isfinite(replaced) or (suffix == "kg" and replaced < 0):
                raise ValueError("Invalid replaced thermal inventory")
            deltas["joined_" + suffix] += replaced
            deltas["left_" + suffix] = deltas.get("left_" + suffix, 0.) + replaced
    for key in set(bn["ledger"]) | set(an["ledger"]):
        value = bn["ledger"].get(key)
        if bn["opened"] and key in deltas:
            expected = value + deltas[key]
            # Only summing newly admitted parcels allows rounding, bounded by
            # their count and double precision; existing history stays exact.
            tolerance = max(1e-9, 8*(len(energy)+1)*max(math.ulp(value), math.ulp(expected)))
            if not math.isclose(an["ledger"].get(key, math.nan), expected, rel_tol=0, abs_tol=tolerance):
                raise ValueError(f"New thermal inventory does not close its ledger: {key}, expected {expected}, got {an['ledger'].get(key)}")
        elif an["ledger"].get(key) != value:
            raise ValueError("Staging changed existing thermal ledger history")


#: What the world reports about the machines in it, in the SNAPSHOT's own words
#: rather than the room file's -- a store is "energy_stores" here and "stores"
#: there. An installation may bring its own; it may not touch any already there.
MACHINE_KEYS = ("energy_stores", "motors", "controls", "programs", "solar_panels")


def _machine_bodies(row):
    """Which bodies one machine row names."""
    named = []
    for key in ("body", "on"):
        value = row.get(key) if isinstance(row, dict) else None
        if isinstance(value, str):
            named.append(value)
        elif isinstance(value, (list, tuple)):
            named += [str(v) for v in value if isinstance(v, str)]
    return named


def _appended_machines(before, after, added):
    """Old machines exactly as they were, new ones only on the new bodies.

    A room may already hold a hoist or a rover. Installing a driven cart adds
    stores, motors and controls of its own, so the snapshot legitimately grows
    -- but nothing that was already running may move, and nothing new may reach
    for a body that was there before.
    """
    for key in MACHINE_KEYS:
        old = before.get(key) or []
        current = after.get(key) or []
        if not isinstance(current, list) or not isinstance(old, list):
            continue
        if len(current) < len(old) or current[:len(old)] != old:
            raise ValueError(f"Staging changed existing {key}; installation refused")
        for row in current[len(old):]:
            # A readout need not name its bodies -- the engine fills a motor's
            # "on" from the joints, which travel only when their set changes, so
            # a snapshot can leave it empty. What it DOES name must be new; that
            # it names nothing is not evidence of anything.
            reached = set(_machine_bodies(row))
            if reached and not reached <= set(added):
                raise ValueError(f"An added {key[:-1]} reaches a body that was already there; "
                                 "installation refused")


def _appended_joints(before, after, added, definitions):
    """Verify old constraint history and the declared new-body hinge frames."""
    old, current = before.get("joints", []), after.get("joints", [])
    if len(current) != len(old)+len(definitions) or not _joint_readouts_match(old, current[:len(old)]):
        raise ValueError("Staging changed existing joints or added unexpected constraints")
    bodies = {b["name"]:b for b in after["bodies"]}

    def rotate(q, v):
        w,x,y,z=q
        t=[2*(y*v[2]-z*v[1]),2*(z*v[0]-x*v[2]),2*(x*v[1]-y*v[0])]
        return [v[0]+w*t[0]+y*t[2]-z*t[1],v[1]+w*t[1]+z*t[0]-x*t[2],v[2]+w*t[2]+x*t[1]-y*t[0]]

    def near(a,b):
        return len(a)==len(b) and all(type(x) in (int,float) and math.isfinite(x) and abs(x-y)<=1e-7 for x,y in zip(a,b))

    for i,(joint,definition) in enumerate(zip(current[len(old):],definitions)):
        a,b=definition["a"],definition["b"]
        if definition.get("kind")!="hinge" or a not in added or b not in added or a==b:
            raise ValueError("New assembly constraints must be hinges between its new bodies")
        if (joint.get("id")!=before["next"]["joint"]+i or joint.get("kind")!="hinge"
                or joint.get("a")!=a or joint.get("b")!=b or joint.get("attached") is not True):
            raise ValueError("Staging changed an added hinge's identity or endpoints")
        point=[v/1000 for v in definition["at_mm"]]
        for end,name in (("a",a),("b",b)):
            pose=bodies[name]["pose"]
            offset=rotate(pose["q_wxyz"],joint["point_local_"+end])
            if not near([pose["com_m"][k]+offset[k] for k in range(3)],point):
                raise ValueError("Staging changed an added hinge's attachment point")
        axis=definition["axis"];length=math.sqrt(sum(v*v for v in axis))
        if not near(rotate(bodies[a]["pose"]["q_wxyz"],joint["axis_local_a"]),[v/length for v in axis]):
            raise ValueError("Staging changed an added hinge's axis")
        expected={"lower":math.radians(definition.get("lower_deg",-180)),
                  "upper":math.radians(definition.get("upper_deg",180)),
                  "friction":definition.get("friction_n_m",0)}
        if any(not math.isclose(joint.get(k,math.nan),v,rel_tol=0,abs_tol=1e-12) for k,v in expected.items()):
            raise ValueError("Staging changed an added hinge's limits or friction")
        held=joint.get("held") or {}
        if any(not math.isclose(held.get(k,math.nan),v,rel_tol=0,abs_tol=1e-6)
               for k,v in (("lower",expected["lower"]),("upper",expected["upper"]),("at",0.))):
            raise ValueError("Staging changed an added hinge's native solver limits or initial angle")
        if joint.get("member_end")!=-1 or joint.get("declared_kept") or joint.get("parted_because"):
            raise ValueError("Staging added undeclared hinge material or failure state")
        for key in ("breaks_at_n","comes_off_n","holds_shear_n","holds_tension_n","stiffness_n_m",
                    "damping_n_s_m","rated_breaks_at_n","rated_shear_n","rated_tension_n",
                    "declared_breaks_at_n","declared_shear_n","declared_tension_n","declared_stiffness_n_m"):
            if joint.get(key)!=0:
                raise ValueError("Staging added an undeclared hinge capacity")


def _preserved(before: dict[str, Any], after: dict[str, Any], root: str | set[str], *, thermal_transfer=None, added_joints=()) -> None:
    """Append-only carry must keep the serialized physical state, not just poses.

    Exact body and part equality also establishes unchanged node/bond index
    ranges before comparing damage/plastic arrays. Unknown future global state
    is compared, not ignored. New heat lumps may be appended by the compiler;
    stored thermal histories remain exact and new network membership is accounted.
    """
    added = {root} if isinstance(root, str) else root
    if any(t["body"] not in added for t in _transfers(thermal_transfer)):
        raise ValueError("Thermal transfer may only initialize the new output")
    current = {b["name"]: b for b in after["bodies"]}
    prior = {b["name"]: b for b in before["bodies"]}
    if len(current) != len(after["bodies"]) or set(current) != set(prior) | added:
        raise ValueError("Staging did not preserve the exact existing body set")
    for name, body in prior.items():
        if body != current[name]:
            raise ValueError(f"Staging changed existing physical state for {name}; installation refused")
    parts = {tuple(p["bodies"]): p for p in after["parts"]}
    for part in before["parts"]:
        if parts.get(tuple(part["bodies"])) != part:
            raise ValueError("Staging changed existing topology or material declarations")
    exceptions = {"bodies", "parts", "fingerprint", "spec_digest", "next", "heat", "joints",
                  "material_geometry", *MACHINE_KEYS}
    _appended_joints(before, after, added, added_joints)
    _appended_machines(before, after, added)
    for key in set(before) | set(after):
        if key in exceptions:
            continue
        was, now = before.get(key), after.get(key)
        if was == now:
            continue
        # The world numbers what it makes, so bringing a motor or a store moves
        # that counter on. It may go forward and never back: a counter that fell
        # would mean an id about to be handed out twice.
        if str(key).startswith("next") and type(now) is int and (was is None or (type(was) is int and now >= was)):
            # Absent before: the first of its kind was just made, and the
            # world began to count them.
            continue
        raise ValueError(f"Staging changed existing {key}; installation refused")
    bg, ag = before.get("material_geometry"), after.get("material_geometry")
    if bg is not None or ag is not None:
        if not isinstance(bg, dict) or not isinstance(ag, dict):
            raise ValueError("Staging changed material geometry schema")
        if {k:v for k,v in bg.items() if k != "records"} != {k:v for k,v in ag.items() if k != "records"}:
            raise ValueError("Staging changed material geometry metadata")
        br, ar = bg.get("records", {}), ag.get("records", {})
        if not isinstance(br, dict) or not isinstance(ar, dict) or not set(ar) <= set(current):
            raise ValueError("Staging has invalid material geometry bodies")
        if any(ar.get(name) != state for name, state in br.items()) or set(ar) - set(br) - added:
            raise ValueError("Staging changed existing material geometry")
    bnext, anext = before.get("next", {}), after.get("next", {})
    increments={"body":len(added),"joint":len(added_joints)}
    if set(bnext) != set(anext) or any(anext[k] != v+increments.get(k,0) for k,v in bnext.items()):
        raise ValueError("Staging changed unrelated native identifiers")
    bh, ah = before.get("heat"), after.get("heat")
    if bh is not None:
        _thermal_preserved(bh, ah, set(current), thermal_transfer)


def _stage(app, live, old, spec, snapshot, matter, root, shift):
    staging = live_session.Live()
    scratch = SimpleNamespace(engine_path=app.engine_path, runs_path=app.runs_path,
                              live_inprocess=False, on_live_reply=None)
    try:
        terrain_before = _terrain_state(old)
        if "water" in snapshot:
            spec.setdefault("water", {})["state"] = deepcopy(snapshot["water"])
        opened = staging.open(scratch, {"spec": deepcopy(spec), "snapshot": snapshot, "carry": True}, carry_from=old)
        restored = opened.get("restored") or {}
        if restored.get("tier") != "carried" or restored.get("not_carried"):
            raise ValueError("The native engine could not carry the original world unchanged")
        if any(opened.get(k) for k in ("joint_problems", "machine_problems", "blade_problems", "tool_point_problems")):
            raise ValueError("Staging could not restore every existing joint, control or tool")
        saved = _snapshot(staging)
        if _terrain_state(staging.session) != terrain_before:
            raise ValueError("Staging changed terrain or carried excavated material")
        if matter.get("schema") == workshop_articulation.SCHEMA:
            roots={group["root_body"] for group in matter["groups"]}
            _preserved(snapshot, saved, roots, added_joints=matter["joints"])
            for group in matter["groups"]:
                sparse.verify_engine_matter(saved, group["matter"], group["root_body"], placement_grid=shift)
        elif matter.get("schema") == workshop_rigid.SCHEMA:
            _preserved(snapshot, saved, root)
            precise_rigid.verify(saved, matter, root)
        elif matter.get("schema") == "banjo.rigid-assembly.v1":
            # Exact bodies on pins: each is there, exact, with the mass its
            # parts have; and the pins are the design's.
            _preserved(snapshot, saved, root, added_joints=matter["joints"])
            have = {b["name"]: b for b in saved["bodies"]}
            for body in matter["bodies"]:
                found = have.get(body["name"])
                if found is None or found.get("mechanical_model") != precise_rigid.MODEL:
                    raise ValueError("Native precise rigid body is missing or not exact: " + body["name"])
        else:
            _preserved(snapshot, saved, root)
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


def _with_needs(app: Any, design: Any, answer: dict[str, Any]) -> dict[str, Any]:
    """Say what making this would take, and keep it with the preview.

    A design is previewed whatever the rack holds -- the refusal belongs at
    ``commit``, where material actually leaves the rack -- so the page can show
    the shortfall and still let the person keep designing.
    """
    needs = workshop_library.what_it_needs(app, design)
    answer["needs"] = needs
    answer["can_be_made"] = needs["enough"]
    entry = _preview_cache(app).get(answer.get("preview_id"))
    if entry is not None:
        entry["needs"] = needs
    return answer


def preview(app: Any, body: Any) -> dict[str, Any]:
    body = _object(body, {"session", "scene", "mode", "candidate", "position_m", "places"})
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
        if models == {"rigid"} and (workshop_articulation.has_bearings(design) or workshop_machines.of(design)):
            # A machine, or anything on pins, asked for exactly: exact bodies
            # on pins, as the room's rover is made (rigid_assembly).
            return _with_needs(app, design, _preview_exact(app, room, live, old, design, overrides, pos,
                                                           body.get("candidate"), body.get("places")))
        if models == {"rigid"}:
            return _with_needs(app, design, _preview_rigid(app, room, live, old, design, overrides, pos))
        workshop_rigid.require_lattice(design, "Live-room prototype installation")
        if workshop_articulation.has_bearings(design):
            return _with_needs(app, design, _preview_articulated(app, room, live, old, design, overrides, pos, body["candidate"]))
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
        horizontal = (round(pos[0]/h), 0, round(pos[1]/h))
        translated = {tuple(g[a]+horizontal[a] for a in range(3)) for g in cells}
        floor = _terrain_floor(old, _bounds(translated,h))
        shift = (horizontal[0], math.ceil(floor/h)-min(g[1] for g in cells), horizontal[2])
        placed = {tuple(g[a]+shift[a] for a in range(3)) for g in cells}
        root = "workshop-" + uuid.uuid4().hex[:16]
        # Decomposed component by component, so every box still says which part
        # of the product it is and the joints declared in the Workshop have
        # something to name once the product is standing in the room (#20).
        # Moving every cell by the same whole number of cells leaves which
        # component each one is untouched. The labels carry the root, because a
        # room may hold two of the same design and a joint in one of them is not
        # a joint in the other.
        placed_parts = {tuple(g[a]+shift[a] for a in range(3)): f"{root}/{name}"
                        for g, name in sparse._grid_parts(matter).items()}
        labelled = sparse.decompose_by_part(placed, placed_parts)
        boxes = [box for box, _ in labelled]
        if len(boxes)>sparse.MAX_SCENE_BOXES or sparse.cells_from_boxes(boxes)!=placed:
            raise ValueError("Prototype geometry cannot be represented exactly within the native scene limit")
        added = [sparse._box_body(root if i==0 else f"{root}-{i}", box, h, next(iter(materials)), root, part)
                 for i,(box,part) in enumerate(labelled)]
        saved = _snapshot(live)
        _clearance(saved, placed, h)
        spec = deepcopy(room.spec)
        spec["bodies"] = spec["bodies"] + added
        from mcp import core_use
        spec["actions"] = spec.get("actions", []) + [core_use.installed(design, root)]
        from mcp import interaction_points
        com = [sum((g[a]+0.5)*h for g in cells)/len(cells) for a in range(3)]
        spec["interaction_points"] = spec.get("interaction_points", []) + [interaction_points.installed(design, root, com)]
        # What each of its joints leaves the bonds that cross it, so a blow
        # landing on it in the room breaks it where it is actually weak rather
        # than treating every joint as the solid wood.
        declared = joint_efficiency.scene_interfaces(design, prefix=f"{root}/")
        # Every one of them has to be a joint the room can still recognise as it
        # is edited: two parts meeting across a face. One that the cell grid
        # leaves apart would be honoured by the engine now -- its bonds reach
        # further than a face -- and then silently dropped the first time the
        # chat rewrote the room, so the joint would quietly become solid wood.
        # Refused here, where it can still be said.
        if len(fracture_lab.standing_interfaces(added, declared)) != len(declared):
            raise ValueError(
                "At this cell size some of the prototype's joints do not meet face to face, so they "
                "could not be kept as the room is edited. Use a finer cell or move the parts to touch")
        if declared:
            spec["interfaces"] = (spec.get("interfaces") or []) + declared
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
                        "spec": spec, "matter": matter, "root": root, "shift": shift,
                        "candidate_hash": _hash(body["candidate"])}
        return _with_needs(app, design, answer)



def _preview_articulated(app, room, live, old, design, overrides, pos, candidate):
    h = float(old.spec["cell_m"])
    prefix = "workshop-" + uuid.uuid4().hex[:16]
    artifact = workshop_articulation.compile_design(design, overrides, cell_m=h, root=prefix)
    actions, points = workshop_articulation.installed_interactions(design, artifact)
    cells = set().union(*(sparse._grid_set(g["matter"]) for g in artifact["groups"]))
    horizontal = (round(pos[0]/h), 0, round(pos[1]/h))
    translated = {tuple(g[a]+horizontal[a] for a in range(3)) for g in cells}
    floor = _terrain_floor(old, _bounds(translated, h))
    shift = (horizontal[0], math.ceil(floor/h)-min(g[1] for g in cells), horizontal[2])
    placed = {tuple(g[a]+shift[a] for a in range(3)) for g in cells}
    saved = _snapshot(live)
    _clearance(saved, placed, h)
    for body in artifact["bodies"]:
        body["center_mm"] = [body["center_mm"][a]+shift[a]*h*1000 for a in range(3)]
    for joint in artifact["joints"]:
        joint["at_mm"] = [joint["at_mm"][a]+shift[a]*h*1000 for a in range(3)]
    spec = deepcopy(room.spec)
    for field, extra in (("bodies", artifact["bodies"]), ("joints", artifact["joints"]),
                         ("interfaces", artifact["interfaces"]), ("actions", actions), ("interaction_points", points)):
        spec[field] = (spec.get(field) or []) + extra
    # What drives it, named by component on the bench and by body in the room.
    # A room may already hold machines, so each kind is added to rather than
    # replaced -- installing a cart must not retire somebody else's hoist.
    made = workshop_machines.installed(design, artifact["component_to_body"])
    if made:
        machines = deepcopy(spec.get("machines") or {})
        for kind, rows in made.items():
            if kind == "schema":
                continue
            machines[kind] = (machines.get(kind) or []) + rows
        spec["machines"] = machines
    fracture_lab.validate(spec)
    roots = {g["root_body"] for g in artifact["groups"]}
    staged, _ = _stage(app, live, old, spec, saved, artifact, roots, shift)
    staged.session.close()
    token = uuid.uuid4().hex
    root = artifact["component_to_body"][design.parameters["primary_use_component"]]
    answer = {"schema":SCHEMA, "status":"preview", "preview_id":token,
              "scene":room.scene, "session":old.id, "mode":"authoring", "root_body":root,
              "root_bodies":sorted(roots), "component_to_body":artifact["component_to_body"],
              "source_joints":artifact["source_joints"], "design_id":design.design_id,
              "matter_physics_hash":artifact["physics_hash"], "cell_size_m":h,
              "cells":len(cells), "mass_kg":artifact["mass_kg"],
              "material_mass_kg":artifact["material_mass_kg"], "requested_position_m":pos,
              "placement_grid":list(shift), "applied_translation_m":[s*h for s in shift],
              "bounds_m":_bounds(placed,h), "engine_grid_verified":True,
              "existing_state_preserved":True, "resources_charged":False,
              "strength_certified":False, "expires_in_s":PREVIEW_TTL_S,
              "limits":"Articulated lattice assembly with ideal hinges; bearing strength and wear are uncalibrated. No manufactured ground anchors or whole-assembly bag storage."}
    cache = _preview_cache(app)
    while len(cache)>=MAX_PREVIEWS: del cache[next(iter(cache))]
    cache[token] = {"expires":time.monotonic()+PREVIEW_TTL_S, "answer":deepcopy(answer),
                    "source_hash":_hash([saved,room.spec,_inventory(room)]),
                    "spec":spec, "matter":artifact, "root":roots, "shift":shift,
                    "candidate_hash":_hash(candidate)}
    return answer


def _default_places(pos, routine):
    """Where a routine works when the install names no places: its dig site
    three metres ahead (+z) of where it is set down, its depot three metres
    behind. Said in the receipt, so the person can move them."""
    import machine_routine
    spec = machine_routine.ROUTINES.get(routine.get("kind") or "roam") or {}
    out = {}
    for i, name in enumerate(spec.get("places") or []):
        out[name] = [round(pos[0], 3), round(pos[1] + (3.0 if i == 0 else -3.0), 3)]
    return out


def _goods_for(spec, made, design, frame, pos):
    """A machine that processes (docs/machine-world.md, "Raw materials into
    finished goods"): its intake and its output are stockpiles of the room's.
    Named after a component of the design (a bin), each is made where that
    part stands, under the machine's own name; named otherwise, where the
    machine is set down, a metre and a half ahead and behind. The recipes the
    routine brings are given to the room where it lacks them."""
    import machine_goods
    for program in made.get("programs") or []:
        routine = program.get("routine")
        if not isinstance(routine, dict):
            continue
        recipes = routine.pop("recipes", None) or []
        if routine.get("kind") != "process" and not recipes:
            continue
        goods = spec.get("goods")
        if not isinstance(goods, dict):
            goods = spec["goods"] = {"deposits": [], "stockpiles": [], "recipes": []}
        for key in ("deposits", "stockpiles", "recipes"):
            goods.setdefault(key, [])
        parts = {p.name: p for p in getattr(design, "parts", [])}
        for role, ahead in (("intake", 1.5), ("output", -1.5)):
            name = routine.get(role)
            if not name:
                continue
            if any(s.get("name") == name for s in goods["stockpiles"]):
                continue                             # the room's own, by name
            part = parts.get(name)
            if part is not None:
                at = frame[0](part.center_m)
                xz = [round(float(at[0]), 3), round(float(at[2]), 3)]
                pile_name = f"{program['name']} {name}"
            else:
                xz = [round(float(pos[0]), 3), round(float(pos[1]) + ahead, 3)]
                pile_name = name
            n, base = 1, pile_name
            while any(s.get("name") == pile_name for s in goods["stockpiles"]):
                n += 1
                pile_name = f"{base} {n}"
            goods["stockpiles"].append({"name": pile_name, "at_m": xz, "radius_m": 1.0, "holds": {}})
            routine[role] = pile_name
        for recipe in recipes:
            if not any(r.get("name") == recipe.get("name") for r in goods["recipes"]):
                goods["recipes"].append(deepcopy(recipe))
        if routine.get("recipe") and not any(r.get("name") == routine["recipe"] for r in goods["recipes"]):
            raise ValueError(f"the room has no recipe called {routine['recipe']!r}; declare it on the routine "
                             f"(recipes) or pick one the room knows: "
                             + (", ".join(repr(r.get("name")) for r in goods["recipes"]) or "none"))
        spec["goods"] = machine_goods.checked(goods)


def _named_apart(existing, made):
    """A machine's names, kept apart from the room's: a second rover's battery
    is "rover battery 2", its program "rover 2", and whatever names them --
    a motor its store, a program its wheels' controls -- follows. The room
    refuses two stores of one name, and a design does not know the room."""
    taken = {kind: {row.get("name") for row in existing.get(kind) or [] if isinstance(row, dict)}
             for kind in ("stores", "controls", "programs", "panels")}
    renamed = {}
    out = deepcopy(made)
    for kind in ("stores", "controls", "programs", "panels"):
        for row in out.get(kind) or []:
            name = row.get("name")
            if name is None:
                continue
            new, n = name, 1
            while new in taken[kind]:
                n += 1
                new = f"{name} {n}"
            taken[kind].add(new)
            if new != name:
                renamed[(kind, name)] = new
                row["name"] = new
    for motor in out.get("motors") or []:
        motor["store"] = renamed.get(("stores", motor.get("store")), motor.get("store"))
    for panel in out.get("panels") or []:
        panel["store"] = renamed.get(("stores", panel.get("store")), panel.get("store"))
    for program in out.get("programs") or []:
        for side in ("left", "right"):
            if side in program:
                program[side] = renamed.get(("controls", program.get(side)), program.get(side))
        if program.get("rotors"):
            program["rotors"] = [renamed.get(("controls", r), r) for r in program["rotors"]]
    return out


def _preview_exact(app, room, live, old, design, overrides, pos, candidate, places):
    """A design installed as exact rigid bodies on pins (rigid_assembly): its
    rigid groups as compounds of their own parts, its bearings as hinges, and
    what drives it in the room's own words, sensors and panels carried from the
    design's frame to where it stands. Set down at `pos` facing +z, lifted so
    nothing starts below the ground."""
    import rigid_assembly
    saved = _snapshot(live)
    if saved.get("carry_readiness", {}).get("precise_rigid_version") != 1:
        raise ValueError("Rebuild the native live engine for precise rigid installation; this binary does not declare support")
    root = "workshop-" + uuid.uuid4().hex[:16]
    artifact = rigid_assembly.compile_design(design, overrides, root=root)
    flat = rigid_assembly.placed(artifact, [pos[0], 0.0, pos[1]], 0.0, 0.0)
    lift = 0.0
    for low, lo, hi in rigid_assembly.footprint(flat):
        floor = _terrain_floor(old, ((lo[0], low, lo[1]), (hi[0], low, hi[1]))) if room.spec.get("terrain") else 0.0
        lift = max(lift, floor + 0.002 - low)
    origin = [pos[0], lift, pos[1]]
    set_down = rigid_assembly.placed(artifact, origin, 0.0, 0.0)
    bodies = rigid_assembly.scene_bodies(set_down)
    pins = rigid_assembly.scene_joints(set_down)
    actions, points = rigid_assembly.room_entries(design, set_down)
    # Points and directions of the design's frame in the room's: set down
    # facing +z with no turn, a point moves by the origin and a direction is
    # unchanged.
    frame = (lambda p: [float(p[k]) + origin[k] for k in range(3)], lambda d: [float(v) for v in d])
    record = workshop_machines.of(design)
    routine = ((record.get("programs") or [{}])[0]).get("routine") if record else None
    if routine and not places:
        places = _default_places(pos, routine)
    if places is not None and (not isinstance(places, dict) or len(places) > 16):
        raise ValueError("places maps at most 16 names to [x, z] in the room's metres")
    made = workshop_machines.installed(design, set_down["component_to_body"], frame, places)
    spec = deepcopy(room.spec)
    made = _named_apart(spec.get("machines") or {}, made)
    spec["precise_rigid_bodies"] = spec.get("precise_rigid_bodies", []) + bodies
    for field, extra in (("joints", pins), ("actions", actions), ("interaction_points", points)):
        spec[field] = (spec.get(field) or []) + extra
    if made:
        machines = deepcopy(spec.get("machines") or {})
        for kind, rows in made.items():
            if kind == "schema":
                continue
            machines[kind] = (machines.get(kind) or []) + rows
        spec["machines"] = machines
        _goods_for(spec, made, design, frame, pos)
    # Admission before any new process; this does not rewrite old declarations.
    normalised = precise_rigid.normalise(spec["precise_rigid_bodies"], spec)
    spec["precise_rigid_bodies"] = normalised
    new_names = {b["name"] for b in bodies}
    for body in normalised:
        if body["name"] not in new_names:
            continue
        bounds = precise_rigid.bounds(body["parts"], body["position_m"], body["orientation_wxyz"])
        for existing in saved["bodies"]:
            if "parked" in existing:
                continue
            lo, hi = _body_bounds(existing, float(old.spec["cell_m"]))
            if all(bounds[0][a] < hi[a]+.001 and bounds[1][a] > lo[a]-.001 for a in range(3)):
                raise ValueError("Prototype placement overlaps the current collision envelope of " + existing["name"])
    fracture_lab.validate(spec)
    roots = set(new_names)
    staged, _ = _stage(app, live, old, spec, saved, set_down, roots, None)
    staged.session.close()
    token = uuid.uuid4().hex
    mass = sum(sum(rigid_assembly._mass(p) for p in design.parts if p.name in b["_components"]) for b in set_down["bodies"])
    answer = {"schema": SCHEMA, "status": "preview", "preview_id": token,
              "scene": room.scene, "session": old.id, "mode": "authoring", "root_body": root,
              "root_bodies": sorted(roots), "component_to_body": set_down["component_to_body"],
              "source_joints": set_down["source_joints"], "design_id": design.design_id,
              "mechanical_model": precise_rigid.MODEL, "cell_size_m": float(old.spec["cell_m"]),
              "cells": 0, "mass_kg": round(mass, 4), "requested_position_m": pos,
              "placement_grid": None, "applied_translation_m": origin, "machines": made,
              "places": places or {}, "engine_grid_verified": False,
              "native_precise_geometry_verified": True, "existing_state_preserved": True,
              "resources_charged": False, "strength_certified": False, "expires_in_s": PREVIEW_TTL_S,
              "limits": "Exact bodies on ideal pins: no bearing strength, wear or friction; no internal failure. "
                        + precise_rigid.LIMITS}
    cache = _preview_cache(app)
    while len(cache) >= MAX_PREVIEWS:
        del cache[next(iter(cache))]
    cache[token] = {"expires": time.monotonic()+PREVIEW_TTL_S, "answer": deepcopy(answer),
                    "source_hash": _hash([saved, room.spec, _inventory(room)]),
                    "spec": spec, "matter": set_down, "root": roots, "shift": None,
                    "candidate_hash": _hash(candidate)}
    return answer


def _preview_rigid(app, room, live, old, design, overrides, pos):
    artifact = workshop_rigid.compile_rigid(design, overrides)
    saved = _snapshot(live)
    if saved.get("carry_readiness", {}).get("precise_rigid_version") != 1:
        raise ValueError("Rebuild the native live engine for precise rigid installation; this binary does not declare support")
    root = "workshop-" + uuid.uuid4().hex[:16]
    body, translation = precise_rigid.placement(artifact, root, pos)
    # On ground that is not a plane, on the ground under it: the highest vertex
    # anywhere under its footprint, and the same 2 mm clear -- the owner's rule
    # that nothing starts below the ground. A flat floor answers 0 and leaves
    # it where placement put it.
    if room.spec.get("terrain"):
        lo, _ = seated = precise_rigid.bounds(body["parts"], body["position_m"], body["orientation_wxyz"])
        lift = _terrain_floor(old, seated) + .002 - lo[1]
        body["position_m"][1] += lift
        translation[1] += lift
    spec = deepcopy(room.spec)
    spec["precise_rigid_bodies"] = spec.get("precise_rigid_bodies", []) + [body]
    from mcp import core_use
    spec["actions"] = spec.get("actions", []) + [core_use.installed(design, root)]
    from mcp import interaction_points
    spec["interaction_points"] = spec.get("interaction_points", []) + [
        interaction_points.installed(design, root, artifact["centre_of_mass_m"])]
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

def _admit_fabricated_heat(staged, before, root, expected_mass, temperature):
    transfers, saved = _admit_fabricated_outputs(staged, before, {root: expected_mass}, temperature)
    return transfers[0], saved


def _admit_fabricated_outputs(staged, before, outputs, temperature):
    """Transfer the process's cold output into its native material parcel.

    Called only on the private staged world, after exact mechanical admission.
    Any implicit ambient parcel belongs to this new body alone; replacing it is
    an explicit leave/join crossing, never a reset of previously installed heat.
    """
    names = {b["name"] for b in before["bodies"]}
    if not outputs or not set(outputs) <= names:
        raise ValueError("Thermal outputs must identify staged bodies")
    if any(type(m) not in (int, float) or not math.isfinite(m) or m <= 0 for m in outputs.values()):
        raise ValueError("Thermal outputs need positive finite material masses")
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("Thermal output temperature must be positive and finite")
    def totals(lump):
        if lump is None: return 0., 0.
        parcels = [lump[zone] for zone in ("surface", "core")]
        energy = math.fsum(p["internal_energy_j"] for p in parcels)
        mass = math.fsum(v[0] for p in parcels for v in struct.iter_unpack("<d", base64.b64decode(p["kg_b64"], validate=True)))
        return energy, mass
    transfers = []
    saved = before
    for root, expected_mass in outputs.items():
        # Declaring one body can activate an ambient parcel on a neighbour.
        # Observe that parcel before replacing it in the next declaration.
        prior = {l["body"]: l for l in (saved.get("heat") or {}).get("lumps", [])}
        replaced_j, replaced_kg = totals(prior.get(root))
        staged.session.send(op="declare", json={"contents":[{"body":root,"temperature_k":temperature}]})
        saved = _snapshot(staged)
        lumps = {l["body"]: l for l in saved["heat"]["lumps"]}
        report = staged.session.send(op="thermo")["thermo"]
        observed = {b["name"]: b for b in report["bodies"]}
        energy, mass = totals(lumps[root])
        if not math.isclose(mass, expected_mass, rel_tol=1e-6, abs_tol=1e-9):
            raise ValueError("Native output thermal mass differs from funded material")
        if any(abs(observed[root][k]-temperature) > 1e-8 for k in ("temperature_k","core_temperature_k")):
            raise ValueError("Native output temperature differs from the process output")
        transfers.append({"body":root,"temperature_k":temperature,"mass_kg":mass,"internal_energy_j":energy,
                "replaced_j":replaced_j,"replaced_kg":replaced_kg,
                "source":"fabrication-cold-output" if temperature == 293.15 else "fabrication-output"})
    return transfers, saved


def commit(app: Any, body: Any, *, funding_job: str | None = None) -> dict[str, Any]:
    body = _object(body, {"session", "scene", "preview_id", "request_id"})
    token = _token(body.get("preview_id"), "preview_id")
    request = _token(body.get("request_id"), "request_id")
    import fabrication_room
    from mcp import fabrication
    with _world(app) as (room, live, old), fabrication_room.LOCK:
        if fabrication_room.active(app) and funding_job is None:
            raise ValueError("This room only accepts finished, material-funded workpieces")
        if body.get("scene") != room.scene:
            raise ValueError("The source room changed")
        receipts = getattr(room, "workshop_installs", [])
        for receipt in receipts:
            if receipt.get("request_id") == request:
                if receipt.get("preview_id") != token or receipt.get("fabrication_job_id") != funding_job:
                    raise ValueError("This request_id was already used for a different installation")
                return {**deepcopy(receipt), "session": old.id, "replayed": True}
        _source(room, old, body); _supported(room, old)
        plan = _preview_cache(app).get(token)
        if plan is None:
            raise ValueError("The preview expired or is no longer available. Preview again")
        if plan["answer"]["session"] != old.id or plan["answer"]["scene"] != room.scene:
            raise ValueError("The preview belongs to a different world session")
        before = _snapshot(live)
        if plan["source_hash"] != _hash([before,room.spec,_inventory(room)]):
            raise ValueError("The world or inventory changed after preview. Preview again; nothing was installed")
        # Material leaves the rack here and nowhere else. A design may be drawn,
        # measured and tried on the bench with an empty rack; it cannot be MADE
        # out of stock that is not there. The fabrication lane funds its own
        # stock, so a funded job is not charged a second time.
        needs = plan.get("needs") if funding_job is None else None
        if needs is not None and not needs.get("enough"):
            raise ValueError("The rack cannot cover this yet: short " + ", ".join(
                f"{m['short_kg']:g} kg of {m['material']}" for m in needs["missing"])
                + ". The design is kept; get the material and make it then")
        fabrication_state = deepcopy(getattr(room, "fabrication_record", None))
        if fabrication_state is not None:
            fabrication.advance(fabrication_state, before["t_s"])
        if funding_job is not None:
            if fabrication_state is None: raise ValueError("No funded material record")
            job = fabrication_state["jobs"].get(funding_job)
            if job is None or _hash(job["candidate"]) != plan.get("candidate_hash"):
                raise ValueError("Preview does not match the funded design and core-use program")
            fabrication_state = fabrication.transfer(fabrication_state, funding_job, plan["answer"], request)
        staged, saved = _stage(app, live, old, plan["spec"], before, plan["matter"], plan["root"], plan["shift"])
        drawn = None
        try:
            thermal_transfer = None
            if funding_job is not None:
                if plan["matter"].get("schema") == workshop_articulation.SCHEMA:
                    outputs = {g["root_body"]:g["mass_kg"] for g in plan["matter"]["groups"]}
                    thermal_transfer, saved = _admit_fabricated_outputs(staged, saved, outputs, fabrication.AMBIENT_K)
                    _preserved(before, saved, plan["root"], thermal_transfer=thermal_transfer, added_joints=plan["matter"]["joints"])
                else:
                    thermal_transfer, saved = _admit_fabricated_heat(staged, saved, plan["root"], job["product_kg"], fabrication.AMBIENT_K)
                    _preserved(before, saved, plan["root"], thermal_transfer=thermal_transfer)
            receipt = {**deepcopy(plan["answer"]), "status": "installed", "request_id": request,
                       "session": staged.session.id, "source_session": old.id, "replayed": False}
            if thermal_transfer is not None:
                receipt["thermal_transfers" if isinstance(thermal_transfer,list) else "thermal_transfer"] = thermal_transfer
            receipt.pop("expires_in_s", None)
            if funding_job is not None:
                receipt.update(mode="fabrication", fabrication_job_id=funding_job, resources_charged=True,
                               limits="Finite stock and work charged; exact native geometry and prior state verified. " + fabrication.LIMITATIONS[0])
            if needs is not None:
                drawn = workshop_library.take_from_rack(app, needs)
                receipt.update(resources_charged=True, materials_taken=drawn["took"], rack=drawn["rack"])
            kept = deepcopy(receipts[-(MAX_RECEIPTS-1):]) + [deepcopy(receipt)]
            record = SimpleNamespace(scene=room.scene, spec=plan["spec"], chat=deepcopy(room.chat),
                                     inventory_record=_inventory(room), world_record=saved, workshop_installs=kept,
                                     gameplay_record=deepcopy(getattr(room,"gameplay_record",None)),
                                     fabrication_record=fabrication_state,
                                     world_upgrades=deepcopy(getattr(room, "world_upgrades", {})))
            # The only fallible persistent write occurs BEFORE the live swap.
            # A failed atomic save leaves the original process and room intact.
            if not app.store.save(record):
                raise ValueError("The room store refused the installation")
        except BaseException:
            # Nothing was installed, so nothing was spent: put the stock back.
            if drawn is not None:
                for row in drawn["took"]:
                    workshop_library.set_rack(app, row["material"], row["left_kg"] + row["took_kg"])
            staged.session.close()
            raise
        room.spec = plan["spec"]
        room.world_record = saved
        room.workshop_installs = kept
        room.fabrication_record = fabrication_state
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
