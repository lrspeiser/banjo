"""Personal opening goals, awarded only from server-owned action evidence.

This is a building tutorial over the existing material-funded authoring lane.
It neither invents a fabrication process nor awards tech-tree knowledge.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

import inventory_room
import logging
import market
import workshop_library
from mcp import workshop, workshop_rigid

SCHEMA = "banjo.starter-goals.v1"
CHAIN = "first-camp-v1"
OPENING_CHAIN = "first-tool-v1"
STEPS = (
    ("bank-solar", "Collect your first energy", "Bank 500 J from the shared solar array.", 500, "J"),
    ("stock-iron", "Gather building supplies", "Buy four iron lots: 4 kg for your own stock.", 4, "kg"),
    ("build-camp", "Build your first camp item", "Make a small iron camp stool in the world.", 1, "build"),
    ("carry-camp", "Pack it for your next adventure", "Put your own camp stool in your bag.", 1, "item"),
)


@lru_cache(maxsize=1)
def _recipe() -> tuple[dict[str, Any], str, float]:
    import playable_recipes
    from mcp import workshop_components
    source=playable_recipes.recipe('stool',design_id='starter-camp-stool')
    design,overrides=workshop_components.design_from_spec(source)
    artifact = workshop_rigid.compile_rigid(design, overrides)
    return ({"kind": design.kind, "design_id": design.design_id,
             "parameters": dict(design.parameters), "component_overrides": overrides},
            artifact["physics_hash"], artifact["mass_kg"])


def recipe() -> dict[str, Any]:
    return deepcopy(_recipe()[0])


def observe(app: Any, owner: str) -> None:
    if not getattr(app, "world_id", None) or not owner:
        return
    try:
        view(app, owner, {})
    except Exception:
        # The native action has already committed. Do not tell the player it
        # failed and encourage a duplicate. A later Goals view retries credit.
        logging.getLogger("banjo").exception("Opening goal evidence could not be recorded")


def _schema(db: Any) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS starter_goal_progress (
        owner_id TEXT NOT NULL, chain_id TEXT NOT NULL, goal_id TEXT NOT NULL,
        evidence_json TEXT NOT NULL, completed_at TEXT NOT NULL,
        PRIMARY KEY(owner_id,chain_id,goal_id))""")


def view(app: Any, owner: str, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body)-{'chain'}:
        raise ValueError("Goals accepts only a checklist selector; completion comes from game actions")
    if not getattr(app, "world_id", None) or not owner:
        raise ValueError("Create or join a named game to begin your first camp")
    import goal_chains
    selected=body.get('chain','active')
    if selected not in (CHAIN,'active',*goal_chains.definitions()):
        raise ValueError('Unknown goal chain')
    if selected != CHAIN:
        camp=view(app,owner,{'chain':CHAIN})
        if selected=='active':
            result=None
            for ident in goal_chains.definitions():
                # Retain the old completed camp as an opening qualification.
                # Its achievements stay available; nobody must buy it again.
                if ident==OPENING_CHAIN and camp['complete']: continue
                result=goal_chains.view(app,owner,ident)
                if not result['complete']: break
        else:
            result=goal_chains.view(app,owner,selected)
        result.update(balance_j=camp['balance_j'],camp_body=camp['camp_body'],
                      unlocked=(not goal_chains.definitions()[result['chain_id']]['after'] or
                        goal_chains.completed(app,owner,goal_chains.definitions()[result['chain_id']]['after']) or
                        (result['chain_id']=='first-workshop-v1' and camp['complete'])),
                      chains=camp['chains'])
        return result
    import json
    with workshop_library._connect(app) as db:
        market._schema(db)
        _schema(db)
        deposits = db.execute("SELECT COALESCE(SUM(joules),0) FROM market_deposits WHERE owner_id=?",
                              (owner,)).fetchone()[0]
        iron_kg = db.execute("SELECT COUNT(*) FROM market_orders WHERE owner_id=? AND item_id='iron-stock'",
                                (owner,)).fetchone()[0]
        balance = market._balance(db, owner)
        completed = {r["goal_id"]: json.loads(r["evidence_json"]) for r in db.execute(
            "SELECT goal_id,evidence_json FROM starter_goal_progress WHERE owner_id=? AND chain_id=?",
            (owner, CHAIN))}
    # A client-chosen design ID is not proof of geometry or who made it.
    # Match the engine-admitted physical hash and the authenticated builder.
    receipts = [r for r in getattr(app.room, "workshop_installs", [])
                if r.get("status") == "installed" and r.get("owner_id") == owner
                and r.get("matter_physics_hash") == _recipe()[1] and r.get("resources_charged")]
    session = getattr(app.live, "session", None)
    shown = inventory_room.shown(app, owner) if session and app.live_holder == "world" else {}
    record = shown.get("record") or {}
    held = set(record.get("stowed") or []) | {n for n in (record.get("hands") or {}).values() if n}
    packed = next((r for r in receipts if r.get("root_body") in held), None)
    if packed:
        # A failed room save must not award a durable achievement for a bag
        # that will disappear on restart. Check the saved guest record too.
        saved = app.store.read_record(app.room.scene)
        saved_bag = ((saved.get("players") or {}).get(owner) or {}).get("inventory") or {}
        saved_held = set(saved_bag.get("stowed") or []) | {
            n for n in (saved_bag.get("hands") or {}).values() if n}
        if packed["root_body"] not in saved_held:
            packed = None
    present = {b.get("name") for key in ("bodies", "precise_rigid_bodies")
               for b in (app.room.spec.get(key) or [])}
    standing = next((r for r in reversed(receipts) if r.get("root_body") in present), None)
    evidence = {
        "bank-solar": {"deposited_j": int(deposits)},
        "stock-iron": {"purchased_kg": iron_kg},
        "build-camp": {"request_id": receipts[-1]["request_id"], "body": receipts[-1]["root_body"],
                       "physics_hash": _recipe()[1]} if receipts else {},
        "carry-camp": {"body": packed["root_body"], "inventory_revision": record.get("revision")} if packed else {},
    }
    values = [deposits, iron_kg, int(bool(receipts)), int(bool(packed))]
    # Remember each demonstrated action even if performed out of order, then
    # the player can spend energy, use supplies, and unpack without losing it.
    with workshop_library._connect(app) as db:
        for (ident, _, _, target, _), value in zip(STEPS, values):
            if value >= target and ident not in completed:
                db.execute("INSERT OR IGNORE INTO starter_goal_progress VALUES (?,?,?,?,?)",
                           (owner, CHAIN, ident, json.dumps(evidence[ident]), workshop_library._now()))
                completed[ident] = evidence[ident]
    rows = [{"id": ident, "title": title, "instruction": instruction, "target": target,
             "value": min(target, max(values[i], target if ident in completed else 0)),
             "unit": unit, "complete": ident in completed, "evidence": completed.get(ident)}
            for i, (ident, title, instruction, target, unit) in enumerate(STEPS)]
    next_goal = next((r["id"] for r in rows if not r["complete"]), None)
    requirements=[{'kind':'energy-deposit','minimum_j':STEPS[0][3]},
        {'kind':'stock-purchase','substance':'iron','remaining_kg':max(0,STEPS[1][3]-rows[1]['value'])},
        {'kind':'admitted-recipe','candidate':recipe()},
        {'kind':'bag-product','body':standing.get('root_body') if standing else None}]
    for row,requirement in zip(rows,requirements):row['requirement']=requirement
    return {"schema": SCHEMA, "chain_id": CHAIN, "title": "Make your first camp",
            "goals": rows, "next_goal": next_goal, "complete": next_goal is None,
            "balance_j": balance, "recipe": recipe(), "recipe_mass_kg": _recipe()[2],
            "camp_body": standing.get("root_body") if standing else None,
            "session": session.id if session and app.live_holder == "world" else None,
            "chains": [*[{'id':c['id'],'title':c['title']} for c in goal_chains.definitions().values()],
                       {'id':CHAIN,'title':'First camp (earlier goals)'}],
            "next_chain": next(iter(goal_chains.definitions())) if next_goal is None else None,
            "unlocked": True,
            "follow_up": "Next: study and use a tool, make a work surface, and learn from a working machine.",
            "limits": ("Building spends iron and native battery energy at the workbench. The stool can be carried; sitting and strength are not tested yet."
                if getattr(app.room,'fabrication_record',None) is not None else
                "Building spends iron. The stool can be carried; sitting and strength are not tested yet. No fabrication energy is charged.")}
