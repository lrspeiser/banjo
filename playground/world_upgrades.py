"""Append trusted starting equipment without rebuilding the player's state.

These are one-time world-authoring supplies, not resource-funded manufacture.
Every changed-world carry is staged, checked and saved before the live swap.
Unsupported physical state leaves the upgrade pending and the world untouched.
"""
from copy import deepcopy
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import fracture_lab
import live_session
import workshop_install as install

CATALOG = Path(__file__).resolve().parents[1] / "progression/world-upgrades.json"
log = logging.getLogger("banjo")


def catalog(scene):
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    if document.get("schema") != "banjo.world-upgrades.v1":
        raise ValueError("Unsupported starting-world upgrade catalog")
    return [entry for entry in document["upgrades"] if entry["scene"] == scene]


def merge(spec, package):
    """Only self-contained additions: never connect to or replace old matter."""
    result = deepcopy(spec)
    names = {b["name"] for b in package["bodies"]}
    if len(names) != len(package["bodies"]) or not names:
        raise ValueError("Upgrade body names must be unique")
    if names & {b["name"] for b in spec["bodies"]}:
        raise ValueError("Starting equipment conflicts with existing object names")
    for joint in package.get("joints", []):
        if joint["a"] not in names or joint["b"] not in names:
            raise ValueError("An upgrade cannot alter an existing body's connections")
    machines = package.get("machines", {})
    for store in machines.get("stores", []):
        if store["body"] not in names:
            raise ValueError("An upgrade store must belong to new equipment")
    for motor in machines.get("motors", []):
        if not set(motor["on"]) <= names:
            raise ValueError("An upgrade motor must belong to new equipment")
    for action in package.get("actions", []):
        if action["body"] not in names:
            raise ValueError("An upgrade action must belong to new equipment")
    for key in ("bodies", "joints", "actions"):
        result.setdefault(key, []).extend(deepcopy(package.get(key, [])))
    for key in ("stores", "motors", "controls"):
        result.setdefault("machines", {}).setdefault(key, []).extend(deepcopy(machines.get(key, [])))
    fracture_lab.validate(result)
    return result


def verify(before, after, names, additions):
    """Verify append-only state, including unknown future snapshot fields."""
    projected = deepcopy(after)
    counts = {"joints": len(additions.get("joints", []))}
    machines = fracture_lab.normalise_machines(
        additions.get("machines"), additions["bodies"], additions.get("joints", []))
    counts.update(energy_stores=len(machines.get("stores", [])),
                  motors=len(machines.get("motors", [])),
                  controls=len(machines.get("controls", [])))
    for key, count in counts.items():
        prior = before.get(key, [])
        current = after.get(key, [])
        by_id = {x["id"]: x for x in current}
        if len(by_id) != len(current) or len(current) != len(prior) + count:
            raise ValueError(f"Upgrade changed the number of existing {key}")
        try:
            kept = [by_id[x["id"]] for x in prior]
        except KeyError as exc:
            raise ValueError(f"Upgrade lost an existing {key}") from exc
        same = install._joint_readouts_match(prior, kept) if key == "joints" else prior == kept
        if not same:
            raise ValueError(f"Upgrade changed existing {key}")
        projected[key] = kept
    for key, count in (("next_energy_store", counts["energy_stores"]),
                       ("next_motor", counts["motors"]), ("next_control", counts["controls"])):
        if after[key] != before[key] + count:
            raise ValueError(f"Upgrade changed {key} unexpectedly")
        projected[key] = before[key]
    if after["next"]["joint"] != before["next"]["joint"] + counts["joints"]:
        raise ValueError("Upgrade changed joint identifiers unexpectedly")
    projected["next"]["joint"] = before["next"]["joint"]
    install._preserved(before, projected, names)
    # Test the actual old poses, not where their authored geometry once stood.
    old_names = {b["name"] for b in before["bodies"] if not b.get("parked")}
    by_name = {b["name"]: b for b in after["bodies"]}
    h = additions["cell_m"]
    for name in names:
        lo, hi = install._body_bounds(by_name[name], h)
        for old in old_names:
            olo, ohi = install._body_bounds(by_name[old], h)
            if all(min(hi[a], ohi[a]) - max(lo[a], olo[a]) > 1e-6 for a in range(3)):
                raise ValueError(f"Starting equipment would overlap {old}; move it before retrying")


def apply_one(app, package):
    with install._world(app) as (room, live, old):
        ident = package["id"]
        receipts = deepcopy(getattr(room, "world_upgrades", {}))
        if ident in receipts:
            return None, {**receipts[ident], "status": "already_applied"}
        install._source(room, old, {"scene": room.scene, "session": old.id})
        names = {b["name"] for b in package["bodies"]}
        present = names & {b["name"] for b in room.spec["bodies"]}
        if present and present != names:
            raise ValueError("Only part of this starting equipment exists; refusing to replace or duplicate it")
        staged = None
        try:
            if present:
                # A fresh world already has its initial equipment. Recording
                # this fact must never replace modified or depleted equipment.
                spec = room.spec
                saved, why = live.snapshot()
                if saved is None:
                    raise ValueError(f"Cannot record starting equipment: {why}")
                opened = None
                disposition = "present"
            else:
                if room.spec["cell_m"] != package["cell_m"]:
                    raise ValueError("Starting equipment needs the world's original cell resolution")
                before = install._snapshot(live)
                spec = merge(room.spec, package)
                # Changed-scene native carry takes water from the new scene's
                # state field; otherwise it would reopen the authored river.
                if "water" in before:
                    spec.setdefault("water", {})["state"] = deepcopy(before["water"])
                staged = live_session.Live()
                scratch = SimpleNamespace(engine_path=app.engine_path, runs_path=app.runs_path,
                                          live_inprocess=False, on_live_reply=None)
                opened = staged.open(scratch, {"spec": spec, "snapshot": before, "carry": True},
                                     carry_from=old)
                restored = opened.get("restored") or {}
                if restored.get("tier") != "carried" or restored.get("not_carried"):
                    raise ValueError("Starting equipment could not preserve the original world")
                if any(opened.get(k) for k in ("joint_problems", "machine_problems",
                                               "blade_problems", "tool_point_problems")):
                    raise ValueError("Starting equipment could not restore all existing mechanisms")
                saved = install._snapshot(staged)
                verify(before, saved, names, package)
                disposition = "installed"
            receipt = {"id": ident, "title": package["title"], "status": disposition,
                       "package_hash": install._hash(package), "time_s": saved["t_s"],
                       "help": package.get("help", ""),
                       "supplied_as": package["supplied_as"]}
            receipts[ident] = deepcopy(receipt)
            record = SimpleNamespace(**vars(room))
            record.spec, record.world_record, record.world_upgrades = spec, saved, receipts
            if not app.store.save(record):
                raise ValueError("Could not save starting equipment; original world retained")
            room.spec, room.world_record, room.world_upgrades = spec, saved, receipts
            if staged is not None:
                live.session = staged.session
                staged.session = None
                live.session.on_reply = getattr(app, "on_live_reply", None)
                try:
                    old.close()
                except Exception:
                    log.exception("Could not close retired world after startup upgrade")
            return opened, receipt
        finally:
            if staged is not None and staged.session is not None:
                staged.shutdown()


def apply(app, opened):
    """Open/rejoin response includes actionable status without forcing resets."""
    reports = []
    for package in catalog(app.room.scene):
        try:
            changed, receipt = apply_one(app, package)
            if changed is not None:
                opened = {**opened, **changed}
            reports.append(receipt)
        except (ValueError, OSError, live_session.LiveError) as exc:
            reports.append({"id": package["id"], "title": package["title"],
                            "status": "pending", "reason": str(exc)})
    opened["world_upgrades"] = reports
    return opened
