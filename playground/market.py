"""Energy market for a named world: metered solar-grid deposits and stock sales.

The wallet is an economic claim denominated in joules. Depositing draws the
same number of physical joules from the world solar farm. Buying transfers a
finite vendor lot to the authenticated guest's Workshop rack; it does not
pretend that market stock was mined or manufactured by the physics engine.
"""
from __future__ import annotations

import math
import re
import threading
from typing import Any

import gameplay_room
import workshop_library
import world_access

REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
LOTS = (
    # id, name, category, kg per lot, starting lots, base joules per lot
    ("oak-stock", "Oak stock", "material", "oak", 0.5, 60, 120),
    ("iron-stock", "Iron stock", "material", "iron", 0.25, 48, 190),
    ("glass-stock", "Glass stock", "material", "glass", 0.25, 40, 170),
    ("rubber-stock", "Rubber stock", "material", "rubber", 0.25, 36, 170),
    ("copper-batch", "Copper batch", "goods", "copper", 0.5, 36, 260),
    ("wire-coil", "Copper wire coil", "goods", "copper wire", 0.5, 36, 330),
)
BY_ID = {row[0]: row for row in LOTS}
_lock = threading.RLock()


def _schema(db: Any) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS market_wallet (
            owner_id TEXT PRIMARY KEY, balance_j INTEGER NOT NULL DEFAULT 0 CHECK(balance_j >= 0));
        CREATE TABLE IF NOT EXISTS market_stock (
            item_id TEXT PRIMARY KEY, remaining INTEGER NOT NULL CHECK(remaining >= 0),
            initial INTEGER NOT NULL CHECK(initial > 0), last_restock_tick INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS market_orders (
            request_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, item_id TEXT NOT NULL,
            price_j INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS market_deposits (
            request_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, joules INTEGER NOT NULL,
            store_name TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    if "last_restock_tick" not in {r["name"] for r in db.execute("PRAGMA table_info(market_stock)")}:
        db.execute("ALTER TABLE market_stock ADD COLUMN last_restock_tick INTEGER NOT NULL DEFAULT 0")
    for item_id, _, _, _, _, initial, _ in LOTS:
        db.execute("INSERT OR IGNORE INTO market_stock(item_id,remaining,initial) VALUES (?,?,?)",
                   (item_id, initial, initial))
    db.commit()


def _balance(db: Any, owner: str) -> int:
    row = db.execute("SELECT balance_j FROM market_wallet WHERE owner_id=?", (owner,)).fetchone()
    return int(row[0]) if row else 0


def _price(base: int, initial: int, remaining: int) -> int:
    # Bounded scarcity: each lot is costlier as this world's vendor runs low.
    # No player-specific discounts, so the quote is auditable and race-safe.
    return int(math.ceil(base * (1 + 0.75 * (initial - remaining) / initial)))


def _restock(app: Any, db: Any) -> None:
    # The external trader delivers one lot of each item per two minutes of
    # simulated world time, up to its shelf capacity. Solar makes the currency
    # renewable; this explicit supplier keeps the goods side renewable too.
    session = getattr(getattr(app, "live", None), "session", None)
    live_t = (getattr(session, "state", {}) or {}).get("t") if session else None
    saved_t = (getattr(getattr(app, "room", None), "world_record", None) or {}).get("t_s")
    tick = max(0, int(float(live_t if live_t is not None else saved_t or 0) // 120))
    for row in db.execute("SELECT item_id,remaining,initial,last_restock_tick FROM market_stock"):
        last = int(row["last_restock_tick"])
        if tick > last:
            db.execute("UPDATE market_stock SET remaining=?,last_restock_tick=? WHERE item_id=?",
                       (min(int(row["initial"]), int(row["remaining"]) + tick - last), tick,
                        row["item_id"]))
    db.commit()


def _offers(db: Any) -> list[dict[str, Any]]:
    stock = {r["item_id"]: r for r in db.execute("SELECT * FROM market_stock")}
    out = []
    for item_id, label, kind, substance, kg, _, base in LOTS:
        row = stock[item_id]
        remaining, initial = int(row["remaining"]), int(row["initial"])
        out.append({"id": item_id, "name": label, "kind": kind, "substance": substance,
                    "mass_kg": kg, "remaining": remaining, "initial": initial,
                    "price_j": _price(base, initial, remaining), "base_j": base})
    return out


def _guidance(app: Any, offers: list[dict[str, Any]]) -> dict[str, Any]:
    import workshop_tabs
    skills = workshop_tabs.skills(app)
    next_skill = next((t for t in skills["techniques"] if t["within_reach"]), None)
    recipes = workshop_tabs.recipes(app)["templates"]
    available = {o["substance"]: o for o in offers if o["remaining"] > 0}
    candidates = []
    for recipe in recipes:
        if recipe.get("problem") or recipe.get("source") != "built-in":
            continue
        if not (recipe.get("readiness") or {}).get("ready_as_drawn"):
            continue
        for missing in recipe.get("missing") or []:
            offer = available.get(missing["what"])
            if offer:
                gap = float(missing.get("short_kg", 0))
                covers = gap <= offer["mass_kg"] + 1e-4
                candidates.append((not covers, recipe.get("short_share", 1),
                                   offer["price_j"], recipe["name"], offer["id"], gap))
    candidates.sort()
    chosen = candidates[0] if candidates else None
    return {"skill": ({"id": next_skill["id"], "name": next_skill["name"],
                        "route": next((r["says"] for r in next_skill["earned_by"]
                                       if r.get("world_ready",True)), "")}
                       if next_skill else None),
            "recipe": chosen[3] if chosen else None,
            "offer_id": chosen[4] if chosen else None,
            "gap_kg": chosen[5] if chosen else None,
            "covers_gap": not chosen[0] if chosen else False}


def _settle(app: Any) -> None:
    with world_access.state_lock(app):
        _settle_locked(app)


def _settle_locked(app: Any) -> None:
    """Credit saved native draws exactly once, including after a crash/restart."""
    room = getattr(app, "room", None)
    durable = getattr(room, "market_durable_pending", set())
    for receipt in list(getattr(room, "market_pending", []) or []):
        if receipt["request_id"] not in durable:
            continue
        with workshop_library._connect(app) as db:
            _schema(db)
            db.execute("BEGIN IMMEDIATE")
            was = db.execute("SELECT 1 FROM market_deposits WHERE request_id=?",
                             (receipt["request_id"],)).fetchone()
            if not was:
                db.execute("INSERT INTO market_deposits VALUES (?,?,?,?,?)",
                           (receipt["request_id"], receipt["owner_id"], receipt["joules"],
                            receipt["store_name"], workshop_library._now()))
                db.execute("INSERT INTO market_wallet(owner_id,balance_j) VALUES (?,?) "
                           "ON CONFLICT(owner_id) DO UPDATE SET balance_j=balance_j+excluded.balance_j",
                           (receipt["owner_id"], receipt["joules"]))
    # The SQL receipt is permanent; remove paired room claims once settled.
    old = list(getattr(room, "market_pending", []) or [])
    if durable and all(r["request_id"] in durable for r in old):
        room.market_pending = [r for r in old if r["request_id"] not in durable]
        try:
            with gameplay_room.LOCK, app.world_lock:
                if app.store.save(room):
                    return
        except (OSError, ValueError, TypeError):
            pass
        room.market_pending = old
        room.market_durable_pending = durable


def _bank(app: Any, owner: str, body: dict[str, Any], keep_world: Any) -> None:
    request_id = body.get("request_id")
    joules = body.get("joules")
    if not isinstance(request_id, str) or not REQUEST.fullmatch(request_id):
        raise ValueError("Banking needs a request id")
    if isinstance(joules, bool) or not isinstance(joules, int) or not 1 <= joules <= 500:
        raise ValueError("Bank 1 to 500 whole joules at a time")
    room = getattr(app, "room", None)
    if room is None or getattr(app, "live_holder", None) != "world" or app.live.session is None:
        raise ValueError("Open your world before banking solar energy")
    with world_access.gate(app).enter(exclusive=True), world_access.state_lock(app), gameplay_room.LOCK:
        pending = getattr(room, "market_pending", None)
        if not isinstance(pending, list):
            pending = room.market_pending = []
        old = next((r for r in pending if r["request_id"] == request_id), None)
        if old:
            if old["owner_id"] != owner or old["joules"] != joules:
                raise ValueError("This request id already names another deposit")
            if request_id not in getattr(room, "market_durable_pending", set()):
                if (not keep_world(app, "retrying an energy bank save") or
                        request_id not in getattr(room, "market_durable_pending", set())):
                    raise ValueError("The banked energy still awaits a durable world save")
            _settle(app)
            return
        with workshop_library._connect(app) as db:
            _schema(db)
            old = db.execute("SELECT owner_id,joules FROM market_deposits WHERE request_id=?",
                             (request_id,)).fetchone()
            if old:
                if old["owner_id"] != owner or old["joules"] != joules:
                    raise ValueError("This request id already names another deposit")
                return
        session = app.live.session.id
        before, refused = app.live.snapshot()
        if before is None:
            raise ValueError("The world must be saveable before energy can be banked: " + refused)
        state = app.live.act({"session": session, "op": "poses"})
        stores = ((state.get("machines") or {}).get("stores") or [])
        source = next((s for s in stores if s.get("body") == "solar farm"), None)
        if source is None:
            raise ValueError("This world has no solar farm to bank from")
        # Leave a reserve for the world machines that share this grid.
        if float(source["charge_j"]) - joules < 0.05 * float(source["capacity_j"]):
            raise ValueError("The solar farm must keep 5% charge for its machines")
        drawn = app.live.act({"session": session, "op": "draw", "store": source["id"], "joules": joules})
        measured = drawn.get("store") or {}
        if measured.get("id") != source["id"] or measured.get("given_j") is None:
            raise ValueError("The energy draw gave no meter reading")
        pending.append({"request_id": request_id, "owner_id": owner,
                        "joules": joules, "store_name": source["name"],
                        "store_id": source["id"], "given_after_j": measured["given_j"]})
        if not keep_world(app, "energy banked from the solar farm"):
            # The live debit and pending claim stay paired in memory. A later
            # successful world checkpoint can settle them; a restart before
            # that checkpoint restores the old charge and discards the claim.
            raise ValueError("The banked energy awaits a durable world save; retry this request id")
        if request_id not in getattr(room, "market_durable_pending", set()):
            raise ValueError("The banked energy awaits a durable world save; retry this request id")
        _settle(app)


def _buy(app: Any, owner: str, body: dict[str, Any]) -> None:
    item_id, request_id = body.get("item_id"), body.get("request_id")
    if not isinstance(item_id, str) or item_id not in BY_ID:
        raise ValueError("Unknown market item")
    if not isinstance(request_id, str) or not REQUEST.fullmatch(request_id):
        raise ValueError("Buying needs a request id")
    _, _, kind, substance, kg, _, base = BY_ID[item_id]
    with workshop_library._connect(app) as db:
        _schema(db)
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT owner_id,item_id FROM market_orders WHERE request_id=?",
                         (request_id,)).fetchone()
        if old:
            if old["owner_id"] != owner or old["item_id"] != item_id:
                raise ValueError("This request id already names another order")
            return
        row = db.execute("SELECT remaining,initial FROM market_stock WHERE item_id=?",
                         (item_id,)).fetchone()
        if row["remaining"] < 1:
            raise ValueError("This item is sold out")
        price = _price(base, row["initial"], row["remaining"])
        if body.get("quoted_price_j") != price:
            raise ValueError("The market price changed; refresh before buying")
        if _balance(db, owner) < price:
            raise ValueError("You need more banked energy for this item")
        db.execute("UPDATE market_wallet SET balance_j=balance_j-? WHERE owner_id=?", (price, owner))
        db.execute("UPDATE market_stock SET remaining=remaining-1 WHERE item_id=?", (item_id,))
        table = "workshop_material_rack" if kind == "material" else "workshop_goods_rack"
        column = "material" if kind == "material" else "substance"
        db.execute(f"INSERT INTO {table}(owner_id,{column},mass_kg,updated_at) VALUES (?,?,?,?) "
                   f"ON CONFLICT(owner_id,{column}) DO UPDATE SET "
                   "mass_kg=mass_kg+excluded.mass_kg,updated_at=excluded.updated_at",
                   (owner, substance, kg, workshop_library._now()))
        db.execute("INSERT INTO market_orders VALUES (?,?,?,?,?)",
                   (request_id, owner, item_id, price, workshop_library._now()))


def request(app: Any, owner: str, body: Any, keep_world: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or body.get("action", "view") not in ("view", "bank", "buy"):
        raise ValueError("Expected a Market view, bank or buy request")
    if len(body) > 4:
        raise ValueError("Market request has too many fields")
    with _lock:
        _settle(app)
        with workshop_library._connect(app) as db:
            _schema(db)
            _restock(app, db)
        action = body.get("action", "view")
        if action == "bank":
            _bank(app, owner, body, keep_world)
        elif action == "buy":
            _buy(app, owner, body)
        with workshop_library._connect(app) as db:
            _schema(db)
            balance, offers = _balance(db, owner), _offers(db)
            history = [dict(r) for r in db.execute(
                "SELECT item_id,price_j,created_at FROM market_orders WHERE owner_id=? "
                "ORDER BY created_at DESC LIMIT 10", (owner,))]
        return {"schema": "banjo.market.v1", "balance_j": balance, "offers": offers,
                "bankable": getattr(app, "live_holder", None) == "world" and app.live.session is not None,
                "guidance": _guidance(app, offers), "orders": history,
                "pricing": "Base price rises by up to 75% as finite world stock is sold."}
