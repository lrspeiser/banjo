"""Personal Workshop product/component library backed by SQLite.

Library identity is user-scoped from day one.  Items also carry normalized tags
by semantic namespace (physics, interface, relationship, capability, test,
role, family), so the library can be browsed by *how something behaves* rather
than only by names such as cart or kettle.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import time
import uuid
from typing import Any, Iterable

from mcp import engine_materials
from mcp.workshop import WorkshopDesign

LIBRARY_SCHEMA = "banjo.workshop-library.v1"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_TAG_NAMESPACE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
DEFAULT_PRICES = {
    "oak": 3.00, "iron": 1.20, "aluminum": 4.00, "glass": 1.50,
    "alumina ceramic": 6.00, "rubber": 2.50, "ice": 0.10, "concrete": 0.15,
}
#: What the rack starts with, in kilograms. A design may be drawn, measured and
#: tried on the bench whatever the rack holds; only MAKING it draws on these.
DEFAULT_RACK = {
    "oak": 12.4, "iron": 6.2, "aluminum": 0.0, "glass": 0.6,
    "alumina ceramic": 0.0, "rubber": 1.1, "ice": 0.0, "concrete": 40.0,
}


def owner_id(app: Any) -> str:
    return str(getattr(app, "workshop_owner_id", "owner") or "owner")[:120]


def db_path(app: Any) -> Path:
    explicit = getattr(app, "workshop_db", None)
    if explicit:
        path = Path(explicit)
    elif getattr(app, "runs_path", None) is not None:
        path = Path(app.runs_path).resolve().parent / "banjo.db"
    elif getattr(app, "workshop_store", None) is not None:
        path = Path(app.workshop_store).resolve() / "banjo.db"
    else:
        path = Path(__file__).resolve().parents[1] / "build" / "workshop" / "banjo.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _open_connection(app: Any) -> sqlite3.Connection:
    db = sqlite3.connect(db_path(app), timeout=5.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS workshop_library_items (
            item_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            item_type TEXT NOT NULL CHECK(item_type IN ('component','assembly')),
            name TEXT NOT NULL,
            family TEXT,
            role TEXT,
            current_version INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS workshop_library_owner
            ON workshop_library_items(owner_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS workshop_library_versions (
            item_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            owner_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            PRIMARY KEY(item_id, version),
            FOREIGN KEY(item_id) REFERENCES workshop_library_items(item_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS workshop_library_tags (
            item_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY(item_id, owner_id, namespace, value),
            FOREIGN KEY(item_id) REFERENCES workshop_library_items(item_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS workshop_library_tag_lookup
            ON workshop_library_tags(owner_id, namespace, value, item_id);
        CREATE TABLE IF NOT EXISTS workshop_material_prices (
            owner_id TEXT NOT NULL,
            material TEXT NOT NULL,
            price_per_kg REAL NOT NULL,
            currency TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(owner_id, material)
        );
        CREATE TABLE IF NOT EXISTS workshop_material_rack (
            owner_id TEXT NOT NULL,
            material TEXT NOT NULL,
            mass_kg REAL NOT NULL CHECK(mass_kg >= 0),
            updated_at TEXT NOT NULL,
            PRIMARY KEY(owner_id, material)
        );
        CREATE TABLE IF NOT EXISTS workshop_bench_presets (
            owner_id TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            name TEXT NOT NULL,
            test_name TEXT NOT NULL,
            config_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(owner_id, preset_id)
        );
        CREATE TABLE IF NOT EXISTS workshop_goods_rack (
            owner_id TEXT NOT NULL,
            substance TEXT NOT NULL,
            mass_kg REAL NOT NULL CHECK(mass_kg >= 0),
            updated_at TEXT NOT NULL,
            PRIMARY KEY(owner_id, substance)
        );
    """)
    who, now = owner_id(app), _now()
    for material, price in DEFAULT_PRICES.items():
        db.execute("""INSERT OR IGNORE INTO workshop_material_prices
                    (owner_id, material, price_per_kg, currency, updated_at)
                    VALUES (?, ?, ?, 'credits', ?)""", (who, material, price, now))
    for material, mass in DEFAULT_RACK.items():
        db.execute("""INSERT OR IGNORE INTO workshop_material_rack
                    (owner_id, material, mass_kg, updated_at)
                    VALUES (?, ?, ?, ?)""", (who, material, mass, now))
    db.commit()
    return db


@contextmanager
def _connect(app: Any):
    db = _open_connection(app)
    try:
        with db:
            yield db
    finally:
        db.close()


def _id(value: Any | None = None) -> str:
    if value:
        item = str(value)
        if not _SAFE.fullmatch(item):
            raise ValueError("library item id must be letters, digits, dot, dash or underscore")
        return item
    return "lib-" + uuid.uuid4().hex[:16]


def _payload(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > 512 * 1024:
        raise ValueError("Workshop library item exceeds 512 KB")
    return text


def normalize_tags(value: Any) -> dict[str, list[str]]:
    if value in (None, {}): return {}
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError("library tags must be an object of namespace to values")
    out: dict[str, list[str]] = {}
    for namespace, values in value.items():
        namespace = str(namespace).strip().lower()
        if not _TAG_NAMESPACE.fullmatch(namespace):
            raise ValueError(f"invalid tag namespace {namespace!r}")
        if isinstance(values, str): values = [values]
        if not isinstance(values, (list, tuple, set)):
            raise ValueError(f"{namespace} tags must be a list")
        cleaned = sorted({str(tag).strip().lower().replace(" ", "_")[:80]
                          for tag in values if str(tag).strip()})
        if len(cleaned) > 200: raise ValueError(f"too many {namespace} tags")
        if cleaned: out[namespace] = cleaned
    return out


def infer_tags(item_type: str, payload: Any) -> dict[str, list[str]] | None:
    """Derive searchable semantics from known physical recipe payloads.

    ``None`` means the payload is not a semantic recipe we understand, so an
    update must preserve any tags already stored for that item.  A known recipe
    returns a complete tag set (possibly empty), allowing its physics index to
    evolve with the actual saved component/design rather than stale metadata.
    """
    if not isinstance(payload, dict):
        return None
    schema = str(payload.get("schema") or "")

    if item_type == "component" and schema == "banjo.workshop-component-recipe.v1":
        ports = payload.get("ports") or []
        interfaces = [str(port.get("kind")) for port in ports
                      if isinstance(port, dict) and port.get("kind")]
        return normalize_tags({
            "physics": payload.get("physics_tags") or [],
            "capability": payload.get("capabilities") or [],
            "interface": interfaces,
            "role": [payload["role"]] if payload.get("role") else [],
            "family": [payload["family"]] if payload.get("family") else [],
        })

    if item_type == "assembly" and schema == "banjo.workshop-assembly-recipe.v1":
        # Import lazily: library storage is used by Workshop's API, while these
        # adapters also know how to rebuild a recipe through authoritative
        # Workshop geometry. Keeping it lazy avoids turning module import order
        # into part of the persistence contract.
        from mcp import workshop_components, workshop_graph
        from mcp.product_graph import physics_tags
        design, _ = workshop_components.design_from_spec(payload)
        from mcp.workshop_matter_metrics import has_physical_skin
        if has_physical_skin(design):
            return normalize_tags({"role": sorted({p.role for p in design.parts}),
                                   "family": sorted({p.family for p in design.parts if p.family}),
                                   "evidence": ["requires-retest"]})
        return normalize_tags(physics_tags(workshop_graph.product(design)))

    if schema == "banjo.product-graph.v1" and isinstance(payload.get("physics_tags"), dict):
        return normalize_tags(payload["physics_tags"])
    return None


def _tags(db: sqlite3.Connection, who: str, item_id: str) -> dict[str, list[str]]:
    rows = db.execute("""SELECT namespace,value FROM workshop_library_tags
                       WHERE owner_id=? AND item_id=? ORDER BY namespace,value""",
                      (who, item_id)).fetchall()
    out: dict[str, list[str]] = {}
    for row in rows: out.setdefault(row["namespace"], []).append(row["value"])
    return out


def save_item(app: Any, *, item_type: str, name: str, payload: dict[str, Any],
              family: str | None = None, role: str | None = None,
              item_id: str | None = None, tags: dict[str, Iterable[str]] | None = None) -> dict[str, Any]:
    if item_type not in {"component", "assembly"}:
        raise ValueError("library item_type must be component or assembly")
    name = " ".join(str(name).split())[:160]
    if not name: raise ValueError("library item needs a name")
    ident = _id(item_id)
    who, now, encoded = owner_id(app), _now(), _payload(payload)
    checked_tags = normalize_tags(tags) if tags is not None else infer_tags(item_type, payload)
    with _connect(app) as db:
        before = db.execute(
            "SELECT current_version FROM workshop_library_items WHERE item_id=? AND owner_id=?",
            (ident, who)).fetchone()
        version = int(before["current_version"]) + 1 if before else 1
        if before:
            db.execute("""UPDATE workshop_library_items SET name=?, family=?, role=?,
                        current_version=?, payload_json=?, updated_at=?
                        WHERE item_id=? AND owner_id=?""",
                       (name, family, role, version, encoded, now, ident, who))
        else:
            db.execute("""INSERT INTO workshop_library_items
                        (item_id,owner_id,item_type,name,family,role,current_version,payload_json,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                       (ident, who, item_type, name, family, role, version, encoded, now, now))
        db.execute("""INSERT INTO workshop_library_versions
                    (item_id,version,owner_id,payload_json,saved_at) VALUES (?,?,?,?,?)""",
                   (ident, version, who, encoded, now))
        if checked_tags is not None:
            db.execute("DELETE FROM workshop_library_tags WHERE item_id=? AND owner_id=?", (ident, who))
            for namespace, values in checked_tags.items():
                for tag in values:
                    db.execute("""INSERT INTO workshop_library_tags(item_id,owner_id,namespace,value)
                                VALUES (?,?,?,?)""", (ident, who, namespace, tag))
    return load_item(app, ident)


def load_item(app: Any, item_id: str) -> dict[str, Any]:
    ident, who = _id(item_id), owner_id(app)
    with _connect(app) as db:
        row = db.execute("SELECT * FROM workshop_library_items WHERE item_id=? AND owner_id=?",
                         (ident, who)).fetchone()
        tags = _tags(db, who, ident) if row is not None else {}
    if row is None: raise FileNotFoundError(f"there is no library item {ident}")
    return {"schema": LIBRARY_SCHEMA, "item_id": row["item_id"], "owner_id": row["owner_id"],
            "item_type": row["item_type"], "name": row["name"], "family": row["family"],
            "role": row["role"], "version": row["current_version"], "tags": tags,
            "payload": json.loads(row["payload_json"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def list_items(app: Any, *, item_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    who = owner_id(app)
    query, args = "SELECT * FROM workshop_library_items WHERE owner_id=?", [who]
    if item_type:
        if item_type not in {"component", "assembly"}: raise ValueError("item_type must be component or assembly")
        query += " AND item_type=?"; args.append(item_type)
    query += " ORDER BY updated_at DESC, item_id LIMIT ?"; args.append(max(1, min(1000, int(limit))))
    with _connect(app) as db:
        rows = db.execute(query, args).fetchall()
        return [{"item_id": r["item_id"], "item_type": r["item_type"], "name": r["name"],
                 "family": r["family"], "role": r["role"], "version": r["current_version"],
                 "updated_at": r["updated_at"], "tags": _tags(db, who, r["item_id"]),
                 "payload": json.loads(r["payload_json"])} for r in rows]


def find_items(app: Any, *, tags: dict[str, Iterable[str]], item_type: str | None = None,
               match_all: bool = True, limit: int = 200) -> list[dict[str, Any]]:
    """Find products/components by physics semantics, always inside one owner's library."""
    wanted = normalize_tags(tags)
    rows = list_items(app, item_type=item_type, limit=max(limit, 1000))
    def matches(row: dict[str, Any]) -> bool:
        have = row.get("tags") or {}
        tests = []
        for namespace, values in wanted.items():
            have_values = set(have.get(namespace) or [])
            tests.extend(tag in have_values for tag in values)
        return all(tests) if match_all else any(tests)
    return [row for row in rows if matches(row)][:max(1, min(1000, int(limit)))]


def pricebook(app: Any) -> dict[str, Any]:
    with _connect(app) as db:
        rows = db.execute("""SELECT material,price_per_kg,currency,updated_at
                           FROM workshop_material_prices WHERE owner_id=? ORDER BY material""",
                          (owner_id(app),)).fetchall()
    return {"currency": "credits", "basis": "starter in-world pricebook; user-configurable, not a retail-price claim",
            "materials": [{"material": r["material"], "price_per_kg": r["price_per_kg"],
                           "currency": r["currency"], "updated_at": r["updated_at"]} for r in rows]}


def set_price(app: Any, material: str, price_per_kg: float, currency: str = "credits") -> dict[str, Any]:
    material, price = engine_materials.canonical(material), float(price_per_kg)
    if price < 0 or price > 1e9: raise ValueError("price_per_kg must be between 0 and 1e9")
    currency = str(currency or "credits")[:24]
    with _connect(app) as db:
        db.execute("""INSERT INTO workshop_material_prices(owner_id,material,price_per_kg,currency,updated_at)
                    VALUES (?,?,?,?,?) ON CONFLICT(owner_id,material) DO UPDATE SET
                    price_per_kg=excluded.price_per_kg,currency=excluded.currency,updated_at=excluded.updated_at""",
                   (owner_id(app), material, price, currency, _now()))
    return pricebook(app)


RACK_SCHEMA = "banjo.workshop-rack.v1"
NEEDS_SCHEMA = "banjo.workshop-needs.v1"
#: The bill rounds masses to four decimal places, so a match can miss by that.
_SLACK_KG = 5e-5


def rack(app: Any) -> dict[str, Any]:
    """What the workshop holds, per material, in kilograms."""
    with _connect(app) as db:
        rows = db.execute("""SELECT material,mass_kg,updated_at FROM workshop_material_rack
                           WHERE owner_id=? ORDER BY material""", (owner_id(app),)).fetchall()
    return {"schema": RACK_SCHEMA, "unit": "kg",
            "materials": [{"material": r["material"], "mass_kg": round(r["mass_kg"], 4),
                           "updated_at": r["updated_at"]} for r in rows]}


def set_rack(app: Any, material: str, mass_kg: float) -> dict[str, Any]:
    material, mass = engine_materials.canonical(material), float(mass_kg)
    if not 0.0 <= mass <= 1e9:
        raise ValueError("mass_kg must be between 0 and 1e9")
    with _connect(app) as db:
        db.execute("""INSERT INTO workshop_material_rack(owner_id,material,mass_kg,updated_at)
                    VALUES (?,?,?,?) ON CONFLICT(owner_id,material) DO UPDATE SET
                    mass_kg=excluded.mass_kg,updated_at=excluded.updated_at""",
                   (owner_id(app), material, mass, _now()))
    return rack(app)


# ---- goods: what machines are made of beyond their matter -------------------------
# The goods rack (docs/machine-world.md, "Raw materials into finished goods"):
# what the workshop holds of the goods the room's machines make -- copper,
# copper wire -- by substance, in kilograms, apart from the material rack of
# oak and iron. A stockpile in the room marked as the rack feeds it; a
# machine's power parts spend it, by this declared table: what each part
# takes per unit of what it is, and at least.
GOODS_PER = {
    "motors": ("copper wire", "stall_torque_n_m", 0.05, 0.5),      # kg per N m of stall, at least 0.5 kg
    "stores": ("copper", "capacity_j", 1.0e-5, 0.5),                # kg per joule of capacity, at least 0.5 kg
    "controls": ("copper wire", None, 0.0, 0.1),
    "panels": ("copper wire", "area_m2", 0.5, 0.1),
}


def goods_rack(app: Any) -> dict[str, Any]:
    """What the workshop holds of goods, per substance, in kilograms."""
    with _connect(app) as db:
        rows = db.execute("""SELECT substance,mass_kg,updated_at FROM workshop_goods_rack
                           WHERE owner_id=? ORDER BY substance""", (owner_id(app),)).fetchall()
    return {"schema": RACK_SCHEMA, "unit": "kg",
            "goods": [{"substance": r["substance"], "mass_kg": round(r["mass_kg"], 4),
                       "updated_at": r["updated_at"]} for r in rows]}


def set_goods(app: Any, substance: str, mass_kg: float) -> dict[str, Any]:
    substance, mass = " ".join(str(substance).split())[:64], float(mass_kg)
    if not substance or not 0.0 <= mass <= 1e9:
        raise ValueError("a substance has a name, and mass_kg is between 0 and 1e9")
    with _connect(app) as db:
        db.execute("""INSERT INTO workshop_goods_rack(owner_id,substance,mass_kg,updated_at)
                    VALUES (?,?,?,?) ON CONFLICT(owner_id,substance) DO UPDATE SET
                    mass_kg=excluded.mass_kg,updated_at=excluded.updated_at""",
                   (owner_id(app), substance, mass, _now()))
    return goods_rack(app)


def add_goods(app: Any, substance: str, mass_kg: float) -> dict[str, Any]:
    """Goods put on the rack, added to what is there (the room's rack
    stockpile, machine_goods.put)."""
    substance, mass = " ".join(str(substance).split())[:64], float(mass_kg)
    if not substance or not 0.0 <= mass <= 1e9:
        raise ValueError("a substance has a name, and mass_kg is between 0 and 1e9")
    with _connect(app) as db:
        db.execute("""INSERT INTO workshop_goods_rack(owner_id,substance,mass_kg,updated_at)
                    VALUES (?,?,?,?) ON CONFLICT(owner_id,substance) DO UPDATE SET
                    mass_kg=workshop_goods_rack.mass_kg+excluded.mass_kg,updated_at=excluded.updated_at""",
                   (owner_id(app), substance, mass, _now()))
    return goods_rack(app)


def goods_needed(design: Any) -> dict[str, float]:
    """The goods a design's machines take to make, by GOODS_PER: nothing for
    a design with no machines."""
    from mcp import workshop_machines
    record = workshop_machines.of(design)
    out: dict[str, float] = {}
    for key, (substance, per, rate, least) in GOODS_PER.items():
        for row in record.get(key) or []:
            amount = max(least, rate * float(row.get(per) or 0.0)) if per else least
            out[substance] = round(out.get(substance, 0.0) + amount, 4)
    return out


def _needs_sentence(rows: list[dict[str, Any]], missing: list[dict[str, Any]]) -> str:
    if not rows:
        return "It takes no material at all."
    takes = ", ".join(f"{r['needed_kg']:g} kg of {r['material']}" for r in rows)
    if not missing:
        return f"It takes {takes}, and the rack has all of it."
    short = ", ".join(f"{m['short_kg']:g} kg of {m['material']}" for m in missing)
    return f"It takes {takes}. You are short {short}."


def what_it_needs(app: Any, design: WorkshopDesign, *, matter_summary=None) -> dict[str, Any]:
    """What making this design would take, against what the rack holds.

    A design is never refused for want of material: it is drawn, measured and
    tried on the bench whatever the rack has.  This is both the answer to "what
    else do I need" and the gate that MAKING it has to pass.
    """
    bom = bill_of_materials(app, design, matter_summary=matter_summary)
    held = {row["material"]: row["mass_kg"] for row in rack(app)["materials"]}
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in bom["materials"]:
        need, have = float(row["mass_kg"]), float(held.get(row["material"], 0.0))
        short = round(max(0.0, need - have), 4)
        rows.append({"material": row["material"], "needed_kg": need, "held_kg": round(have, 4),
                     "short_kg": short, "enough": need - have <= _SLACK_KG})
        if need - have > _SLACK_KG:
            missing.append({"material": row["material"], "short_kg": short})
    # And the goods its machines take, against the goods rack.
    goods_rows: list[dict[str, Any]] = []
    held_goods = {row["substance"]: row["mass_kg"] for row in goods_rack(app)["goods"]}
    for substance, need in sorted(goods_needed(design).items()):
        have = float(held_goods.get(substance, 0.0))
        short = round(max(0.0, need - have), 4)
        goods_rows.append({"substance": substance, "material": substance, "needed_kg": need,
                           "held_kg": round(have, 4), "short_kg": short, "enough": need - have <= _SLACK_KG})
        if need - have > _SLACK_KG:
            missing.append({"material": substance, "substance": substance, "short_kg": short})
    return {"schema": NEEDS_SCHEMA, "unit": "kg", "enough": not missing,
            "materials": rows, "goods": goods_rows, "missing": missing, "basis": bom.get("basis"),
            "material_cost": bom.get("material_cost"), "currency": bom.get("currency"),
            "says": _needs_sentence(rows + goods_rows, missing)}


def take_from_rack(app: Any, needs: dict[str, Any]) -> dict[str, Any]:
    """Draw a design's materials out of the rack: all of them, or none.

    The rack is read again inside the transaction, so two makers cannot spend
    the same oak, and a shortfall raises with what is missing rather than
    quietly making it anyway.
    """
    wanted = {row["material"]: float(row["needed_kg"]) for row in needs.get("materials") or []
              if float(row["needed_kg"]) > 0.0}
    who, now, took = owner_id(app), _now(), []
    with _connect(app) as db:
        held = {r["material"]: float(r["mass_kg"]) for r in db.execute(
            "SELECT material,mass_kg FROM workshop_material_rack WHERE owner_id=?", (who,)).fetchall()}
        missing = [{"material": m, "short_kg": round(want - held.get(m, 0.0), 4)}
                   for m, want in sorted(wanted.items()) if want - held.get(m, 0.0) > _SLACK_KG]
        if missing:
            raise ValueError("the rack is short " + ", ".join(
                f"{m['short_kg']:g} kg of {m['material']}" for m in missing))
        # The goods its machines take, out of the goods rack, in the same
        # transaction: all of it or none.
        goods_wanted = {row["substance"]: float(row["needed_kg"]) for row in needs.get("goods") or []
                        if float(row["needed_kg"]) > 0.0}
        goods_held = {r["substance"]: float(r["mass_kg"]) for r in db.execute(
            "SELECT substance,mass_kg FROM workshop_goods_rack WHERE owner_id=?", (who,)).fetchall()}
        missing += [{"material": s, "substance": s, "short_kg": round(want - goods_held.get(s, 0.0), 4)}
                    for s, want in sorted(goods_wanted.items()) if want - goods_held.get(s, 0.0) > _SLACK_KG]
        if missing:
            raise ValueError("the rack is short " + ", ".join(
                f"{m['short_kg']:g} kg of {m['material']}" for m in missing))
        for material, want in sorted(wanted.items()):
            left = max(0.0, held.get(material, 0.0) - want)
            db.execute("""INSERT INTO workshop_material_rack(owner_id,material,mass_kg,updated_at)
                        VALUES (?,?,?,?) ON CONFLICT(owner_id,material) DO UPDATE SET
                        mass_kg=excluded.mass_kg,updated_at=excluded.updated_at""",
                       (who, material, left, now))
            took.append({"material": material, "took_kg": round(want, 4), "left_kg": round(left, 4)})
        for substance, want in sorted(goods_wanted.items()):
            left = max(0.0, goods_held.get(substance, 0.0) - want)
            db.execute("""INSERT INTO workshop_goods_rack(owner_id,substance,mass_kg,updated_at)
                        VALUES (?,?,?,?) ON CONFLICT(owner_id,substance) DO UPDATE SET
                        mass_kg=excluded.mass_kg,updated_at=excluded.updated_at""",
                       (who, substance, left, now))
            took.append({"material": substance, "substance": substance, "took_kg": round(want, 4),
                         "left_kg": round(left, 4)})
    return {"schema": RACK_SCHEMA, "took": took, "rack": rack(app), "goods_rack": goods_rack(app)}


def save_bench_preset(app: Any, *, name: str, test_name: str, config: dict[str, Any],
                      preset_id: str | None = None) -> dict[str, Any]:
    label = " ".join(str(name).split())[:160]
    if not label: raise ValueError("bench preset needs a name")
    ident = _id(preset_id).replace("lib-", "test-", 1) if preset_id is None else _id(preset_id)
    encoded = _payload(config); now = _now()
    with _connect(app) as db:
        db.execute("""INSERT INTO workshop_bench_presets(owner_id,preset_id,name,test_name,config_json,updated_at)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(owner_id,preset_id) DO UPDATE SET
                    name=excluded.name,test_name=excluded.test_name,config_json=excluded.config_json,updated_at=excluded.updated_at""",
                   (owner_id(app), ident, label, str(test_name)[:80], encoded, now))
    return load_bench_preset(app, ident)


def load_bench_preset(app: Any, preset_id: str) -> dict[str, Any]:
    ident = _id(preset_id)
    with _connect(app) as db:
        row = db.execute("SELECT * FROM workshop_bench_presets WHERE owner_id=? AND preset_id=?",
                         (owner_id(app), ident)).fetchone()
    if row is None: raise FileNotFoundError(f"there is no Workshop test preset {ident}")
    return {"preset_id": row["preset_id"], "name": row["name"], "test": row["test_name"],
            "config": json.loads(row["config_json"]), "updated_at": row["updated_at"]}


def list_bench_presets(app: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    with _connect(app) as db:
        rows = db.execute("""SELECT * FROM workshop_bench_presets WHERE owner_id=?
                           ORDER BY updated_at DESC,preset_id LIMIT ?""",
                          (owner_id(app), max(1, min(500, int(limit))))).fetchall()
    return [{"preset_id": row["preset_id"], "name": row["name"], "test": row["test_name"],
             "config": json.loads(row["config_json"]), "updated_at": row["updated_at"]} for row in rows]


def bill_of_materials(app: Any, design: WorkshopDesign, *, matter_summary=None) -> dict[str, Any]:
    prices = {p["material"]: p for p in pricebook(app)["materials"]}
    grouped: dict[str, dict[str, Any]] = {}
    for part in design.parts:
        material = engine_materials.canonical(part.material)
        try: density = engine_materials.density(material)
        except KeyError: density = None
        mass = part.volume_m3() * density if density is not None else part.mass_kg()
        row = grouped.setdefault(material, {"material": material, "mass_kg": 0.0,
                                             "volume_m3": 0.0, "parts": 0,
                                             "price_per_kg": None, "cost": None})
        row["mass_kg"] += mass; row["volume_m3"] += part.volume_m3(); row["parts"] += 1
    if matter_summary is not None:
        grouped = {row["material"]: {**row, "price_per_kg": None, "cost": None}
                   for row in matter_summary["materials"]}
    total, unpriced = 0.0, []
    for material, row in grouped.items():
        price = prices.get(material); row["mass_kg"] = round(row["mass_kg"], 4)
        row["volume_m3"] = round(row["volume_m3"], 6)
        if price:
            row["price_per_kg"] = float(price["price_per_kg"])
            row["cost"] = round(row["mass_kg"] * row["price_per_kg"], 2); total += row["cost"]
        else: unpriced.append(material)
    return {"schema": "banjo.workshop-bom.v1", "currency": "credits",
            "basis": ("canonical Matter mass; " if matter_summary is not None else "wireframe mass estimate; ") + "starter in-world material pricebook; excludes fabrication, tools, energy and waste",
            "materials": sorted(grouped.values(), key=lambda r: r["material"]),
            "material_cost": round(total, 2), "unpriced_materials": sorted(unpriced)}