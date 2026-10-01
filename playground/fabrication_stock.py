"""Durable SQL escrow for catalog rack stock entering a shared fabrication cell.

The SQL debit and reservation commit together. A room-file failure retains the
reservation, which can be credited once on retry/recovery or explicitly released
only when the durable room contains no receiving receipt. No body is reclaimed.
"""
from __future__ import annotations
from copy import deepcopy
from contextlib import contextmanager
import json
import sqlite3
from mcp import fabrication as model, engine_materials
import workshop_library as library


@contextmanager
def _database(app):
    try:
        with library._connect(app) as db: yield db
    except sqlite3.Error as exc:
        raise OSError("Fabrication stock database unavailable: " + str(exc)) from exc


def _schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS fabrication_stock_reservations (
        scene TEXT NOT NULL, request_id TEXT NOT NULL, requested_by TEXT NOT NULL,
        config_hash TEXT NOT NULL, action_json TEXT NOT NULL, packet_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('reserved','applied','released')),
        release_id TEXT, release_hash TEXT, PRIMARY KEY(scene,request_id))""")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS fabrication_stock_release_ids ON "
               "fabrication_stock_reservations(scene,release_id) WHERE release_id IS NOT NULL")


def _read(row):
    if row is None: return None
    result = dict(row); result["action"] = json.loads(result.pop("action_json"))
    result["packet"] = model.stock_packet(json.loads(result.pop("packet_json")))
    model.token(result["request_id"])
    if (result["packet"]["scene"] != result["scene"] or result["packet"]["requested_by"] != result["requested_by"]
            or result["action"].get("request_id") != result["request_id"]):
        raise ValueError("Stock reservation identity is inconsistent")
    return result


def _owner(app, pool):
    if pool not in ("personal", "shared"): raise ValueError("Stock pool must be personal or shared")
    return library.rack_owner_id(app) if pool == "personal" else "owner"


def _rack(kind):
    if kind == "goods": return "workshop_goods_rack", "substance"
    if kind == "material": return "workshop_material_rack", "material"
    raise ValueError("Unknown stock kind")


def _meter(db, owner, material, kind="material"):
    table, key = _rack(kind)
    row = db.execute(f"SELECT mass_kg FROM {table} WHERE owner_id=? AND {key}=?",
                     (owner, material)).fetchone()
    return {"source_owner": owner, "material": material, "mass_kg": float(row["mass_kg"]) if row else 0.,
            **({"kind": "goods"} if kind == "goods" else {})}


def sources(app, kind="material"):
    """Exact individual balances; shared stock is an explicit choice."""
    result = []
    with _database(app) as db:
        for pool in ("personal", "shared"):
            owner = _owner(app, pool)
            for material in sorted(model.ASSEMBLY_GOODS) if kind == "goods" else library.DEFAULT_RACK:
                meter = _meter(db, owner, material, kind)
                result.append({**meter, "pool": pool, "rack_hash": model.digest(meter)})
    return result


def get(app, scene, ident):
    model.token(ident)
    with _database(app) as db:
        _schema(db)
        return _read(db.execute("SELECT * FROM fabrication_stock_reservations WHERE scene=? AND request_id=?",
                                (scene, ident)).fetchone())


def records(app, scene, *, reserved_only=False):
    with _database(app) as db:
        _schema(db)
        return [_read(row) for row in db.execute("SELECT * FROM fabrication_stock_reservations WHERE scene=? "
            + ("AND status='reserved' " if reserved_only else "")+"ORDER BY request_id", (scene,))]


def pending(app, scene):
    who = library.rack_owner_id(app)
    return [{"reservation_id": r["request_id"], "material": r["packet"]["material"],
        "mass_kg": r["packet"]["mass_kg"], "pool": r["action"]["pool"], "status": r["status"],
        "kind": r["packet"].get("kind", "material")}
        for r in records(app, scene, reserved_only=True) if r["requested_by"] == who]


def reserve(app, scene, state, action):
    """Check receiving capacity first, then atomically debit exactly one rack."""
    who = library.rack_owner_id(app)
    if action.get("requested_by") != who: raise ValueError("Stock requester is not the authenticated owner")
    ident = model.token(action["request_id"])
    material = action["material"]
    if not isinstance(material, str): raise ValueError("Stock needs a material or processed supply name")
    kind = "goods" if action.get("op") == "fund_goods" else "material"
    if kind == "goods":
        model.goods_quantities({material: action["mass_kg"]})
    elif not isinstance(material, str) or not engine_materials.known(material) or engine_materials.canonical(material) != material:
        raise ValueError("Transfer a canonical catalog material, not unprocessed ground or ore")
    mass = model.number(action["mass_kg"], "mass_kg", .000001, 10000)
    owner = _owner(app, action["pool"])
    packet = {"schema": "banjo.fabrication-stock-transfer.v2" if kind == "goods" else "banjo.fabrication-stock-transfer.v1", "scene": scene,
        "source_owner": owner, "requested_by": who, "material": material, "mass_kg": mass,
        "reference_state": "cold-inventory-reservoir-v1"}
    if kind == "goods": packet["kind"] = "goods"
    model.receive_stock(state, action, packet)  # Dry run; cannot strand an invalid credit.
    with _database(app) as db:
        _schema(db); db.execute("BEGIN IMMEDIATE")
        old = _read(db.execute("SELECT * FROM fabrication_stock_reservations WHERE scene=? AND request_id=?",
                              (scene, ident)).fetchone())
        if old:
            if old["action"] != action or old["packet"] != packet or old["config_hash"] != model.digest(state["config"]):
                raise ValueError("Stock request_id already belongs to a different transfer")
            if old["status"] == "released": raise ValueError("This stock reservation was released; use a new request_id")
            return old
        if db.execute("SELECT COUNT(*) FROM fabrication_stock_reservations WHERE scene=?", (scene,)).fetchone()[0] >= 4096:
            raise ValueError("Stock reservation receipt budget exhausted")
        meter = _meter(db, owner, material, kind)
        if action["rack_hash"] != model.digest(meter): raise ValueError("Source rack changed; read stock_sources before spending")
        if mass > meter["mass_kg"]: raise ValueError("Insufficient selected rack stock")
        table, key = _rack(kind)
        db.execute(f"UPDATE {table} SET mass_kg=?,updated_at=? WHERE owner_id=? AND {key}=?",
                   (meter["mass_kg"]-mass, library._now(), owner, material))
        db.execute("INSERT INTO fabrication_stock_reservations VALUES (?,?,?,?,?,?, 'reserved',NULL,NULL)",
            (scene, ident, who, model.digest(state["config"]), json.dumps(action, sort_keys=True), json.dumps(packet, sort_keys=True)))
    return get(app, scene, ident)


def finish(app, record):
    """Called only after the matching receiving receipt was saved durably."""
    with _database(app) as db:
        _schema(db); db.execute("BEGIN IMMEDIATE")
        old = _read(db.execute("SELECT * FROM fabrication_stock_reservations WHERE scene=? AND request_id=?",
                              (record["scene"], record["request_id"])).fetchone())
        if old is None or old["action"] != record["action"] or old["packet"] != record["packet"] or old["status"] == "released":
            raise ValueError("Saved stock credit does not match its SQL reservation")
        db.execute("UPDATE fabrication_stock_reservations SET status='applied' WHERE scene=? AND request_id=?",
                   (record["scene"], record["request_id"]))


def validate(app, scene, state):
    """Every receiving import must have a real, non-released SQL debit."""
    rows = {r["request_id"]: r for r in records(app, scene)}
    if any(r["status"] == "applied" and ident not in state.get("stock_imports", {}) for ident, r in rows.items()):
        raise ValueError("Receiving save is missing previously applied rack stock")
    for ident, packet in state.get("stock_imports", {}).items():
        record = rows.get(ident)
        if (record is None or record["status"] == "released" or record["packet"] != packet
                or record["config_hash"] != model.digest(state["config"])
                or state["receipts"].get(ident) != model.digest(record["action"])):
            raise ValueError("Fabrication stock credit has no matching SQL source reservation")


def settle(app, room, live, state, persist):
    """Recover committed source debits into current-time receiving stock once."""
    model.validate_state(state); validate(app, room.scene, state)
    waiting = records(app, room.scene, reserved_only=True)
    if not waiting: return state
    saved, why = live.snapshot()
    if saved is None: return state  # Pending is visible; no transfer on partial state.
    candidate = deepcopy(state)
    for record in waiting:
        if record["config_hash"] != model.digest(candidate["config"]):
            raise ValueError("Reserved stock belongs to a different station configuration")
        candidate, _ = model.receive_stock(candidate, record["action"], record["packet"])
    # A save may have succeeded but its acknowledgement failed. Persist again
    # at CURRENT native time; never restore old bodies to match that receipt.
    persist(app, room, saved, candidate)
    for record in waiting: finish(app, record)
    return candidate


def release(app, room, state, reservation_id, request_id):
    """An uncredited reservation can return to its exact original rack owner."""
    ident = model.token(reservation_id); release_id = model.token(request_id)
    who = library.rack_owner_id(app)
    action_hash = model.digest({"reservation_id": ident, "request_id": release_id, "requested_by": who})
    record = get(app, room.scene, ident)
    if record is None or record["requested_by"] != who: raise ValueError("This is not your stock reservation")
    if record["status"] == "released":
        if record["release_id"] != release_id or record["release_hash"] != action_hash:
            raise ValueError("Stock reservation already released by a different request")
        return True
    if record["status"] != "reserved" or ident in state.get("stock_imports", {}):
        raise ValueError("Already funded stock cannot be refunded")
    durable = app.store.load(room.scene)
    if durable is None or not isinstance(getattr(durable, "fabrication_record", None), dict):
        raise ValueError("Cannot establish the durable receiving state; reservation is retained")
    if ident in durable.fabrication_record.get("stock_imports", {}):
        raise ValueError("Stock was already credited durably; recover its receiving state")
    with _database(app) as db:
        _schema(db); db.execute("BEGIN IMMEDIATE")
        current = _read(db.execute("SELECT * FROM fabrication_stock_reservations WHERE scene=? AND request_id=?",
                                  (room.scene, ident)).fetchone())
        if current != record: raise ValueError("Stock reservation changed before release")
        packet = record["packet"]
        table, key = _rack(packet.get("kind", "material"))
        db.execute(f"INSERT INTO {table}(owner_id,{key},mass_kg,updated_at) VALUES (?,?,?,?) "
            f"ON CONFLICT(owner_id,{key}) DO UPDATE SET mass_kg=mass_kg+excluded.mass_kg,updated_at=excluded.updated_at",
            (packet["source_owner"], packet["material"], packet["mass_kg"], library._now()))
        db.execute("UPDATE fabrication_stock_reservations SET status='released',release_id=?,release_hash=? "
            "WHERE scene=? AND request_id=?", (release_id, action_hash, room.scene, ident))
    return False
