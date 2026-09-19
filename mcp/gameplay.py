"""Expedition v1: finite surface stocks and a bounded, lumped timber dryer.

The native world's accepted time is the only clock. This is an explicitly
declared demonstration process, not a second rigid-body or terrain solver.
See docs/gameplay.md for its boundary, units and unsupported couplings.
"""
from __future__ import annotations
import base64
from collections import deque
from copy import deepcopy
import hashlib
import json
import math
import random
import struct

VERSION = 1
DAY_S = 1800.0
AMBIENT_K = 293.15
BOIL_K = 373.15
WOOD_J_KG = 16e6
LATENT_J_KG = 2.257e6
CP_WOOD = 1500.0
CP_WATER = 4180.0
CAPACITY_J_K = 4000.0
BUILD = {"stone": 2.0, "dry_wood": 0.5}
KINDS = ("stone", "dry_wood", "wet_wood")


def number(value, name, low=0.0, high=1e9):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + " must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return float(value)


def position(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("at_m must be [x, y, z] in metres")
    return [number(v, "coordinate", -1e5, 1e5) for v in value]


def new(terrain, time_s=0.0, seed=7, water=None):
    """Choose a connected, dry starter area from the engine's actual heightfield.

    Stocks represent loose surface material, additional to the native terrain's
    soil/rock columns. They are never claimed as excavated ore or living trees.
    """
    g = terrain["grid"]
    nx, nz, dx = g["nx"], g["nz"], g["cell_m"]
    if not (3 <= nx <= 1024 and 3 <= nz <= 1024 and 0 < dx <= 10):
        raise ValueError("unsupported starter terrain grid")
    h = struct.unpack("<" + "f" * (nx * nz), base64.b64decode(terrain["heights_b64"], validate=True))
    if not all(math.isfinite(v) for v in h):
        raise ValueError("non-finite terrain")
    # The native valley's water is below its upper terraces. This conservative
    # elevation gate deliberately declines other terrain kinds, tides and floods.
    wet = set()
    if water and water.get("surface_mm_b64"):
        i0, j0, ni, nj = water["box"]
        values = struct.unpack("<" + "H"*(ni*nj), base64.b64decode(water["surface_mm_b64"], validate=True))
        for j in range(nj):
            for i in range(ni):
                k = (j0+j)*nx+i0+i
                v = values[j*ni+i]
                if v and water["base_m"]+v/1000.0 > h[k]+0.02:
                    wet.add(k)
    safe = set()
    for j in range(2, nz - 2):
        for i in range(2, nx - 2):
            k = j * nx + i
            slope = max(abs(h[k] - h[k + d]) / dx for d in (-1, 1, -nx, nx))
            if h[k] >= 0.85 and slope < 0.35 and k not in wet:
                safe.add(k)
    def xyz(k):
        return [g["x0_m"] + (k % nx) * dx, h[k], g["z0_m"] + (k // nx) * dx]
    eye = terrain.get("view", {}).get("eye_m", [0, 2, 0])
    groups = []
    while safe:
        start = min(safe)
        safe.remove(start)
        queue, group = deque([start]), []
        while queue:
            k = queue.popleft()
            group.append(k)
            for d in (-1, 1, -nx, nx):
                q = k + d
                if q in safe:
                    safe.remove(q)
                    queue.append(q)
        if len(group) * dx * dx >= 12.0:
            groups.append(group)
    if not groups:
        raise ValueError("No safe connected starter terrace; choose another valley seed")
    group = min(groups, key=lambda cells: min((xyz(k)[0]-eye[0])**2 + (xyz(k)[2]-eye[2])**2 for k in cells))
    camp = min(group, key=lambda k: (xyz(k)[0]-eye[0])**2 + (xyz(k)[2]-eye[2])**2)
    nearby = [k for k in group if 1.5 <= math.dist(xyz(k), xyz(camp)) <= 7.0]
    rng = random.Random(seed)
    rng.shuffle(nearby)
    picked = []
    for k in nearby:
        if all(math.dist(xyz(k), xyz(p)) > 1.25 for p in picked):
            picked.append(k)
        if len(picked) == 6:
            break
    if len(picked) < 6:
        raise ValueError("Starter materials cannot be reached on this terrace; choose another valley seed")
    kinds = ["stone", "dry_wood", "wet_wood"] * 2
    nodes = [{"id": f"stock-{i+1}", "kind": kind, "at_m": xyz(k),
              "kg": 6.0, "initial_kg": 6.0}
             for i, (k, kind) in enumerate(zip(picked, kinds))]
    here = xyz(camp)
    return {"version": VERSION, "seed": seed, "time_s": number(time_s, "time_s"),
            "spawn_m": [here[0], here[1] + 1.7, here[2]], "camp_m": here,
            "nodes": nodes, "inventory_kg": dict.fromkeys(KINDS, 0.0),
            "inventory_heat_j": dict.fromkeys(KINDS, 0.0),
            "construction_kg": dict.fromkeys(KINDS, 0.0), "construction_heat_j": 0.0,
            "dryer": None, "revision": 0, "receipts": {},
            "initial_material_kg": 36.0, "last_gather_s": -10.0,
            "ledger": {"burned_kg": 0.0, "released_j": 0.0, "ambient_j": 0.0,
                       "oxygen_in_kg": 0.0, "combustion_out_kg": 0.0,
                       "vapor_out_kg": 0.0, "vapor_out_j": 0.0},
            "generation": {"status": "viable", "reachable_area_m2": len(group)*dx*dx,
                           "checks": ["connected dry terrace", "hand gathering needs no tools",
                                      "construction and first-batch stocks", "finite fuel available"]}}


def capacity(d):
    return CAPACITY_J_K + d["wood_kg"]*CP_WOOD + d["water_kg"]*CP_WATER


def temperature(d):
    return AMBIENT_K + d["heat_j"] / capacity(d)


def advance(state, time_s):
    """Advance to accepted native time. Equal time is a no-op; reversal refuses."""
    target = number(time_s, "time_s")
    if target < state["time_s"] - 1e-8:
        raise ValueError("Expedition clock cannot rewind; restore the whole saved world")
    left = max(0.0, target - state["time_s"])
    d = state["dryer"]
    # Fixed maximum thermal step, with no discarded catch-up interval.
    while d and left > 1e-10:
        dt = min(left, 0.25)
        left -= dt
        ledger = state["ledger"]
        # A thermostat bounds normal drying. It is a declared device, not a
        # timer completion bonus: no wet charge, no fuel, or failed -> no burn.
        if d["lit"] and d["water_kg"] > 1e-9 and d["damage"] < 1 and temperature(d) < 413.15:
            burned = min(d["fuel_kg"], 4000.0 * dt / WOOD_J_KG)
            sensible = d["fuel_heat_j"] * burned / d["fuel_kg"] if d["fuel_kg"] else 0
            d["fuel_kg"] -= burned
            d["fuel_heat_j"] -= sensible
            released = burned * WOOD_J_KG
            d["heat_j"] += released * 0.65 + sensible
            ledger["released_j"] += released
            ledger["ambient_j"] += released * 0.35
            ledger["burned_kg"] += burned
            ledger["oxygen_in_kg"] += burned * 1.184
            ledger["combustion_out_kg"] += burned * 2.184
        lost = min(d["heat_j"], 8.0 * (temperature(d)-AMBIENT_K) * dt)
        d["heat_j"] -= lost
        ledger["ambient_j"] += lost
        excess = max(0.0, d["heat_j"] - capacity(d)*(BOIL_K-AMBIENT_K))
        vapor = min(d["water_kg"], excess / LATENT_J_KG)
        carried = vapor * (LATENT_J_KG + CP_WATER*(BOIL_K-AMBIENT_K))
        d["water_kg"] -= vapor
        d["heat_j"] -= carried
        ledger["vapor_out_kg"] += vapor
        ledger["vapor_out_j"] += carried
        if temperature(d) > 453.15:
            d["damage"] = min(1.0, d["damage"] + dt*(temperature(d)-453.15)/6000)
        if d["fuel_kg"] <= 1e-10 or d["water_kg"] <= 1e-9 or d["damage"] >= 1:
            d["lit"] = False
    state["time_s"] = target


def _take(state, kind, kg):
    have = state["inventory_kg"][kind]
    if have + 1e-9 < kg:
        raise ValueError(f"Need {kg:g} kg of {kind}; carrying {have:g} kg")
    heat = state["inventory_heat_j"][kind] * kg / have if have else 0.0
    state["inventory_heat_j"][kind] -= heat
    state["inventory_kg"][kind] = max(0.0, have-kg)
    return heat


def action(state, request):
    """Atomic, retry-safe gameplay action; caller persists before publishing."""
    if not isinstance(request, dict):
        raise ValueError("action must be an object")
    allowed = {"action", "request_id", "at_m", "node", "kg"}
    if set(request)-allowed:
        raise ValueError("Unknown action fields: " + ", ".join(sorted(set(request)-allowed)))
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
        raise ValueError("request_id must be 1 to 80 characters")
    fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False).encode()).hexdigest()
    old = state["receipts"].get(request_id)
    if old:
        if old != fingerprint:
            raise ValueError("request_id was already used for a different action")
        return deepcopy(state)
    out = deepcopy(state)
    at = position(request.get("at_m"))
    op = request.get("action")
    def near(point):
        if math.hypot(at[0]-point[0], at[2]-point[2]) > 2.5 or abs(at[1]-point[1]) > 3:
            raise ValueError("Walk within 2.5 m of the material or drying camp")
    if op == "gather":
        node = next((n for n in out["nodes"] if n["id"] == request.get("node")), None)
        if node is None:
            raise ValueError("Unknown resource node")
        near(node["at_m"])
        kg = number(request.get("kg", 1.0), "kg", 0.01, 2.0)
        if out["time_s"] - out["last_gather_s"] < 1.0-1e-8:
            raise ValueError("Gathering takes one world second between handfuls")
        if node["kg"] + 1e-9 < kg:
            raise ValueError("That surface stock is exhausted")
        if sum(out["inventory_kg"].values()) + kg > 20.0:
            raise ValueError("The material pack carries at most 20 kg")
        node["kg"] = max(0.0, node["kg"]-kg)
        out["inventory_kg"][node["kind"]] += kg
        out["last_gather_s"] = out["time_s"]
    else:
        near(out["camp_m"])
        d = out["dryer"]
        if op == "build":
            if d:
                raise ValueError("The drying camp is already built")
            for kind, kg in BUILD.items():
                out["construction_heat_j"] += _take(out, kind, kg)
                out["construction_kg"][kind] += kg
            out["dryer"] = {"fuel_kg": 0.0, "fuel_heat_j": 0.0, "wood_kg": 0.0,
                            "water_kg": 0.0, "heat_j": 0.0, "damage": 0.0, "lit": False}
        elif d is None:
            raise ValueError("Build the drying camp first: 2 kg stone and 0.5 kg dry wood")
        elif op == "load":
            kg = number(request.get("kg", 1.0), "kg", 0.01, 2.0)
            if d["wood_kg"] > 1e-9:
                raise ValueError("Collect the current batch before loading another")
            d["heat_j"] += _take(out, "wet_wood", kg)
            d["wood_kg"], d["water_kg"] = 0.8*kg, 0.2*kg
        elif op == "fuel":
            kg = number(request.get("kg", 0.2), "kg", 0.001, 0.5)
            if d["fuel_kg"] + kg > 0.5+1e-9:
                raise ValueError("The firebox holds at most 0.5 kg")
            d["fuel_heat_j"] += _take(out, "dry_wood", kg)
            d["fuel_kg"] += kg
        elif op == "light":
            if d["damage"] >= 1 or d["fuel_kg"] <= 0 or d["water_kg"] <= 1e-9:
                raise ValueError("Lighting needs fuel, a wet batch and a working dryer")
            # Ignition enables a bounded combustion law. The spark's negligible
            # energy is excluded; all macroscopic heat comes from consumed fuel.
            d["lit"] = True
        elif op == "extinguish":
            d["lit"] = False
        elif op == "collect":
            if d["wood_kg"] <= 0 or d["water_kg"] > 1e-9:
                raise ValueError("The batch still contains water or is empty")
            if temperature(d) > 333.15:
                raise ValueError("Let the batch cool below 60 C before collecting")
            if sum(out["inventory_kg"].values()) + d["wood_kg"] > 20:
                raise ValueError("The material pack is full; output stays in the dryer")
            product_heat = d["wood_kg"]*CP_WOOD*(temperature(d)-AMBIENT_K)
            out["inventory_kg"]["dry_wood"] += d["wood_kg"]
            out["inventory_heat_j"]["dry_wood"] += product_heat
            d["heat_j"] -= product_heat
            d["wood_kg"] = 0.0
        else:
            raise ValueError("Unknown gameplay action")
    out["revision"] += 1
    out["receipts"][request_id] = fingerprint
    # Keep every receipt in this small personal-world prototype: expiring an
    # idempotency key could spend a retried action twice after a restart.
    return out


def report(state):
    out = deepcopy(state)
    d = state["dryer"]
    l = state["ledger"]
    materials = sum(n["kg"] for n in state["nodes"]) + sum(state["inventory_kg"].values())
    materials += sum(state["construction_kg"].values())
    heat = sum(state["inventory_heat_j"].values()) + state["construction_heat_j"]
    if d:
        materials += d["fuel_kg"]+d["wood_kg"]+d["water_kg"]
        heat += d["heat_j"]+d["fuel_heat_j"]
        out["dryer"]["temperature_k"] = temperature(d)
        out["dryer"]["condition"] = ("failed" if d["damage"] >= 1 else "drying" if d["lit"]
                                    else "ready" if d["wood_kg"] and d["water_kg"] <= 1e-9
                                    else "waiting")
    out["clock"] = {"elapsed_s": state["time_s"], "day": int(state["time_s"]//DAY_S)+1,
                    "day_fraction": (state["time_s"]/DAY_S+0.25)%1,
                    "sun_cycle_s": DAY_S, "offline_policy": "paused"}
    out["audit"] = {
        "material_residual_kg": state["initial_material_kg"]+l["oxygen_in_kg"]-materials
                                -l["combustion_out_kg"]-l["vapor_out_kg"],
        "energy_residual_j": l["released_j"]-heat-l["ambient_j"]-l["vapor_out_j"],
        "stored_heat_j": heat, "boundary": "dryer + surface stocks + material pack"}
    out.pop("receipts")
    return out
