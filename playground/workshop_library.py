"""Personal Workshop product/component library backed by SQLite.

Library identity is user-scoped from day one.  Items also carry normalized tags
by semantic namespace (physics, interface, relationship, capability, test,
role, family), so the library can be browsed by *how something behaves* rather
than only by names such as cart or kettle.
"""
from __future__ import annotations

import json
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


def _connect(app: Any) -> sqlite3.Connection:
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
        CREATE TABLE IF NOT EXISTS workshop_bench_presets (
            owner_id TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            name TEXT NOT NULL,
            test_name TEXT NOT NULL,
            config_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(owner_id, preset_id)
        );
    """)
    who, now = owner_id(app), _now()
    for material, price in DEFAULT_PRICES.items():
        db.execute("""INSERT OR IGNORE INTO workshop_material_prices
                    (owner_id, material, price_per_kg, currency, updated_at)
                    VALUES (?, ?, ?, 'credits', ?)""", (who, material, price, now))
    db.commit()
    return db


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
    checked_tags = normalize_tags(tags) if tags is not None else None
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


def bill_of_materials(app: Any, design: WorkshopDesign) -> dict[str, Any]:
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
    total, unpriced = 0.0, []
    for material, row in grouped.items():
        price = prices.get(material); row["mass_kg"] = round(row["mass_kg"], 4)
        row["volume_m3"] = round(row["volume_m3"], 6)
        if price:
            row["price_per_kg"] = float(price["price_per_kg"])
            row["cost"] = round(row["mass_kg"] * row["price_per_kg"], 2); total += row["cost"]
        else: unpriced.append(material)
    return {"schema": "banjo.workshop-bom.v1", "currency": "credits",
            "basis": "starter in-world material pricebook; excludes fabrication, tools, energy and waste",
            "materials": sorted(grouped.values(), key=lambda r: r["material"]),
            "material_cost": round(total, 2), "unpriced_materials": sorted(unpriced)}
