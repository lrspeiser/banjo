"""Personal Workshop component/design library backed by SQLite.

Banjo currently has one hosted owner rather than account identities. Every row
still carries ``owner_id`` now, so multi-user authentication can later replace
the default ``owner`` without changing the library schema.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
from typing import Any

from mcp import engine_materials
from mcp.workshop import WorkshopDesign

LIBRARY_SCHEMA = "banjo.workshop-library.v1"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
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
        CREATE TABLE IF NOT EXISTS workshop_material_prices (
            owner_id TEXT NOT NULL,
            material TEXT NOT NULL,
            price_per_kg REAL NOT NULL,
            currency TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(owner_id, material)
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


def save_item(app: Any, *, item_type: str, name: str, payload: dict[str, Any],
              family: str | None = None, role: str | None = None,
              item_id: str | None = None) -> dict[str, Any]:
    if item_type not in {"component", "assembly"}:
        raise ValueError("library item_type must be component or assembly")
    name = " ".join(str(name).split())[:160]
    if not name:
        raise ValueError("library item needs a name")
    ident = _id(item_id)
    who, now, encoded = owner_id(app), _now(), _payload(payload)
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
    return load_item(app, ident)


def load_item(app: Any, item_id: str) -> dict[str, Any]:
    ident, who = _id(item_id), owner_id(app)
    with _connect(app) as db:
        row = db.execute("SELECT * FROM workshop_library_items WHERE item_id=? AND owner_id=?",
                         (ident, who)).fetchone()
    if row is None:
        raise FileNotFoundError(f"there is no library item {ident}")
    return {"schema": LIBRARY_SCHEMA, "item_id": row["item_id"], "owner_id": row["owner_id"],
            "item_type": row["item_type"], "name": row["name"], "family": row["family"],
            "role": row["role"], "version": row["current_version"],
            "payload": json.loads(row["payload_json"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def list_items(app: Any, *, item_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    who = owner_id(app)
    query, args = "SELECT * FROM workshop_library_items WHERE owner_id=?", [who]
    if item_type:
        if item_type not in {"component", "assembly"}:
            raise ValueError("item_type must be component or assembly")
        query += " AND item_type=?"; args.append(item_type)
    query += " ORDER BY updated_at DESC, item_id LIMIT ?"; args.append(max(1, min(1000, int(limit))))
    with _connect(app) as db:
        rows = db.execute(query, args).fetchall()
    return [{"item_id": r["item_id"], "item_type": r["item_type"], "name": r["name"],
             "family": r["family"], "role": r["role"], "version": r["current_version"],
             "updated_at": r["updated_at"], "payload": json.loads(r["payload_json"])} for r in rows]


def pricebook(app: Any) -> dict[str, Any]:
    with _connect(app) as db:
        rows = db.execute("""SELECT material,price_per_kg,currency,updated_at
                           FROM workshop_material_prices WHERE owner_id=? ORDER BY material""",
                          (owner_id(app),)).fetchall()
    return {"currency": "credits",
            "basis": "starter in-world pricebook; user-configurable, not a retail-price claim",
            "materials": [{"material": r["material"], "price_per_kg": r["price_per_kg"],
                           "currency": r["currency"], "updated_at": r["updated_at"]} for r in rows]}


def set_price(app: Any, material: str, price_per_kg: float, currency: str = "credits") -> dict[str, Any]:
    material, price = engine_materials.canonical(material), float(price_per_kg)
    if price < 0 or price > 1e9:
        raise ValueError("price_per_kg must be between 0 and 1e9")
    currency = str(currency or "credits")[:24]
    with _connect(app) as db:
        db.execute("""INSERT INTO workshop_material_prices(owner_id,material,price_per_kg,currency,updated_at)
                    VALUES (?,?,?,?,?) ON CONFLICT(owner_id,material) DO UPDATE SET
                    price_per_kg=excluded.price_per_kg,currency=excluded.currency,updated_at=excluded.updated_at""",
                   (owner_id(app), material, price, currency, _now()))
    return pricebook(app)


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
