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
import uuid
from typing import Any
from contextlib import nullcontext

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


def _build_plan(recipe: dict[str, Any], offers: list[dict[str, Any]], balance: int) -> dict[str, Any]:
    """Complete stock estimate; no purchase, reservation or physical admission.

    Use the same per-lot scarcity curve as buying. A stock shortage or a
    substance with no vendor yields no complete quote, rather than pricing
    only the convenient lines and calling that the total.
    """
    available = {o['substance']:o for o in offers}
    lines, partial_cost, complete_cost = [], 0, 0
    for source in [*recipe.get('materials',[]), *recipe.get('goods',[])]:
        name = source.get('material') or source['substance']
        need, held = float(source['kg']), float(source.get('held_kg',0))
        personal, shared = float(source.get('personal_kg',0)), float(source.get('shared_kg',0))
        # This is the rack's existing admission tolerance, not UI rounding.
        gap = max(0.,need-held) if held+5e-5 < need else 0.
        own_draw = min(need,personal)
        shared_draw = min(max(0.,need-own_draw),shared)
        line = {'substance':name, 'needed_kg':need,'held_kg':held,
                'personal_kg':personal,'shared_kg':shared,'gap_kg':gap,
                'debit_personal_kg':own_draw,'debit_shared_kg':shared_draw,
                'status':'covered','lots':0,'cost_j':0,'available_cost_j':0}
        offer = available.get(name)
        if gap and offer:
            lots = max(1,math.ceil(gap/offer['mass_kg']-1e-10))
            now = min(lots,offer['remaining'])
            cost = sum(_price(offer['base_j'],offer['initial'],offer['remaining']-i) for i in range(now))
            line.update(offer_id=offer['id'],lots=lots,lots_available=now,
                        available_cost_j=cost, cost_j=cost if now==lots else None,
                        status='buy' if now==lots else 'stock-short',
                        unavailable_kg=max(0.,gap-now*offer['mass_kg']),
                        next_lot_covers_gap=gap<=offer['mass_kg']+5e-5)
        elif gap:
            line.update(status='no-offer',cost_j=None,unavailable_kg=gap)
        partial_cost += line['available_cost_j']
        if line['cost_j'] is None: complete_cost = None
        elif complete_cost is not None: complete_cost += line['cost_j']
        lines.append(line)
    return {'name':recipe['name'],'source':recipe.get('source'),
            'saved_design_id':recipe.get('saved_design_id'),
            'candidate':{k:recipe.get(k,{}) for k in ('kind','parameters','component_overrides')},
            'lines':lines,'estimated_total_j':complete_cost,'available_cost_j':partial_cost,
            'affordable':complete_cost is not None and complete_cost<=balance,
            'energy_gap_j':max(0,complete_cost-balance) if complete_cost is not None else None,
            'declared_uses':recipe.get('can_do',[]),'goal':None}


def _recommend(recipes: list[dict], offers: list[dict], balance: int, goals: dict | None) -> dict | None:
    import ai_actions
    plans=[]
    for recipe in recipes:
        if recipe.get('problem') or not (recipe.get('readiness') or {}).get('ready_as_drawn'):continue
        plan=_build_plan(recipe,offers,balance)
        if goals and goals.get('unlocked',True):
            preceding=[]
            for row in goals['goals']:
                if row.get('complete') or row.get('done'):continue
                req=row.get('requirement') or {}
                if req.get('kind') in ('admitted-recipe','funded-box-surface') and ai_actions.fits_requirement(recipe,req):
                    plan['goal']={'id':row['id'],'title':row['title'],'chain_id':goals['chain_id'],
                                  'before':list(preceding)}
                    break
                preceding.append(row['title'])
        plans.append(plan)
    # Goal-compatible alternatives can supply the same next capability at
    # different costs. An unrelated cheap object is not progress toward it.
    relevant=[p for p in plans if p['goal']]
    return min(relevant or plans,key=lambda p:(not p['affordable'],
               p['estimated_total_j'] is None,
               p['estimated_total_j'] if p['estimated_total_j'] is not None else math.inf,
               p['name'])) if plans else None


def _guidance(app: Any, offers: list[dict[str, Any]], balance: int) -> dict[str, Any]:
    import workshop_tabs
    skills = workshop_tabs.skills(app)
    next_skill = next((t for t in skills["techniques"] if t["within_reach"]), None)
    goals=None
    if getattr(app,'world_id',None):
        import starter_goals
        goals=starter_goals.view(app,workshop_library.rack_owner_id(app),{'chain':'active'})
    chosen=_recommend(workshop_tabs.recipes(app)['templates'],offers,balance,goals)
    supply=None
    if goals and goals.get('unlocked',True):
        row=next((g for g in goals['goals'] if not g.get('complete') and not g.get('done') and
                  (g.get('requirement') or {}).get('kind')=='stock-purchase'),None)
        if row:
            req=row['requirement']
            supply=_build_plan({'name':row['title'],'materials':[{'material':req['substance'],
                                'kg':req['remaining_kg'],'held_kg':0}]},offers,balance)
            supply['goal']={'id':row['id'],'title':row['title'],'chain_id':goals['chain_id']}
    highlighted=supply or chosen
    gap=next((line for line in highlighted['lines'] if line['status']=='buy'),None) if highlighted else None
    unknown=[t for t in skills['techniques'] if not t['known']]
    blocked=unknown[0] if unknown and not next_skill else None
    return {"skill": ({"id": next_skill["id"], "name": next_skill["name"],
                        "route": next((r["says"] for r in next_skill["earned_by"]
                                       if r.get("world_ready",True)), ""),
                        "locations": [l for r in next_skill['earned_by'] if r.get('world_ready')
                                      for l in r.get('locations',[])]}
                       if next_skill else None),
            'skill_blocked':({'name':blocked['name'],'prerequisites':[n['name'] for n in blocked.get('needs',[]) if not n['known']],
                              'world_missing':blocked.get('world_missing',[])} if blocked else None),
            'plan':chosen,'supply_goal':supply,'recipe':chosen['name'] if chosen else None,
            'offer_id':gap['offer_id'] if gap else None,
            'gap_kg':gap['gap_kg'] if gap else None,
            'covers_gap':gap['next_lot_covers_gap'] if gap else False,
            'estimate_basis':'Whole lots at current stock, including scarcity increases per purchase. No reservation; refresh before buying. Make checks final mass and placement.'}


def _settle(app: Any) -> None:
    with world_access.state_lock(app):
        _settle_locked(app)


def validate_banks(banks: Any) -> None:
    if not isinstance(banks, list):
        raise ValueError("Invalid automatic bank connections")
    seen = set()
    for bank in banks:
        if (not isinstance(bank, dict) or set(bank) != {"owner_id", "store_id", "store_name", "body",
                "reserve_fraction", "exported_j", "panels"} or
                any(not isinstance(bank[k], str) or not bank[k] for k in ("owner_id", "store_name", "body")) or
                type(bank["store_id"]) is not int or bank["store_id"] <= 0 or
                type(bank["exported_j"]) is not int or bank["exported_j"] < 0 or
                type(bank["reserve_fraction"]) not in (int, float) or
                not 0.05 <= bank["reserve_fraction"] <= 1 or
                not isinstance(bank["panels"], list) or not bank["panels"]):
            raise ValueError("Invalid automatic bank connection")
        if bank["store_id"] in seen:
            raise ValueError("A battery cannot credit two owners")
        seen.add(bank["store_id"])
        for panel in bank["panels"]:
            if (not isinstance(panel, dict) or set(panel) != {"id", "name", "body"} or
                    type(panel["id"]) is not int or panel["id"] <= 0 or
                    any(not isinstance(panel[k], str) or not panel[k] for k in ("name", "body"))):
                raise ValueError("Invalid automatic bank panel binding")


def connect_banks(room: Any, saved: dict) -> None:
    """Bind authored bank connections to actual installed stores and owners.

    These bindings outlive the bounded install history. Native machines never
    receive currency metadata. Older built-in arrays acquire the same default.
    """
    banks = getattr(room, "energy_banks", None)
    if banks is None:
        banks = room.energy_banks = []
    for receipt in getattr(room, "workshop_installs", []) or []:
        owner = receipt.get("owner_id")
        if not owner or not receipt.get("resources_charged"):
            continue
        profiles = getattr(room, "player_records", {})
        if profiles and owner not in profiles:
            continue  # Historical anonymous stock is not a player's income.
        recipe = receipt.get("recipe") or {}
        machines = (recipe.get("component_overrides") or {}).get("@machines") or {}
        stores = machines.get("stores") or []
        if recipe.get("kind") == "solar-array" and not stores:
            stores = [{"name":"array battery", "in":"battery", "bank_reserve_fraction":0.05}]
        for declaration in stores:
            reserve = declaration.get("bank_reserve_fraction")
            if reserve is None:
                # Existing built-in arrays predate the connector declaration.
                if recipe.get("kind") != "solar-array":
                    continue
                reserve = 0.05
            body = (receipt.get("component_to_body") or {}).get(declaration.get("in"))
            if not body:
                continue
            candidates = [s for s in saved.get("energy_stores", []) if s.get("body") == body
                          and (s.get("name") == declaration["name"] or
                               s.get("name", "").startswith(declaration["name"] + " "))]
            exact = [s for s in candidates if s["name"] == declaration["name"]]
            candidates = exact or candidates
            if len(candidates) != 1:
                continue  # Ambiguous mapping cannot select somebody else's battery.
            source = candidates[0]
            if any(b["store_id"] == source["id"] for b in banks):
                continue
            panels = [p for p in saved.get("solar_panels", []) if p.get("store") == source["id"]]
            if not panels:
                continue
            banks.append({"owner_id":owner, "store_id":source["id"], "store_name":source["name"],
                          "body":body, "reserve_fraction":reserve, "exported_j":0,
                          "panels":[{"id":p["id"], "name":p["name"], "body":p["body"]} for p in panels]})


def bank_sources(app: Any, owner: str) -> list[dict]:
    """Current source status; generation is not a promise of wallet income."""
    with world_access.state_lock(app):
        room = getattr(app, "room", None)
        if not room or getattr(app, "live_holder", None) != "world" or not app.live.session:
            return []
        state = app.live.act({"session":app.live.session.id, "op":"poses"})
        machines = state.get("machines") or {}
        result = []
        for bank in getattr(room, "energy_banks", []) or []:
            if bank["owner_id"] != owner:
                continue
            source = next((s for s in machines.get("stores", []) if s["id"] == bank["store_id"]
                           and s["name"] == bank["store_name"] and s["body"] == bank["body"]), None)
            if not source:
                continue
            panels = _bank_panels(bank, machines.get("panels", []))
            result.append({"name":source["name"], "stored_j":source["charge_j"],
                           "reserve_j":source["capacity_j"]*bank["reserve_fraction"],
                           "generation_w":sum(p.get("power_w", 0) for p in panels),
                           "banked_j":bank["exported_j"]-sum(r['joules'] for r in getattr(room,'market_pending',[])
                               if r['store_id']==bank['store_id'] and r['owner_id']==owner and
                                  r['request_id'] not in getattr(room,'market_durable_pending',set())),
                           "banking":"automatic"})
        return result


def _bank_panels(bank: dict, panels: list) -> list:
    return [p for p in panels if p.get("store") == bank["store_id"] and
            any(all(p.get(k) == binding[k] for k in ("id", "name", "body")) for binding in bank["panels"])]


def prepare_auto_banks(app: Any, saved: dict) -> bool:
    """Called only inside the world's checkpoint transaction, before saving.

    Draw actual whole joules, limited by collected sunlight and spare charge.
    Initial battery energy and robots' output cannot mint currency. Unsettled
    draws remain paired with their pending receipts through save failures.
    """
    room = app.room
    connect_banks(room, saved)
    pending = getattr(room, "market_pending", None)
    if pending is None:
        pending = room.market_pending = []
    changed = False
    for bank in room.energy_banks:
        if any(r["store_id"] == bank["store_id"] for r in pending):
            continue
        source = next((s for s in saved.get("energy_stores", []) if s["id"] == bank["store_id"]
                       and s["name"] == bank["store_name"] and s["body"] == bank["body"]), None)
        if not source:
            continue
        collected = math.fsum(p["collected_j"] for p in _bank_panels(bank, saved.get("solar_panels", [])))
        # Give all other work first claim on harvested energy. Otherwise a
        # machine could consume its sunlight and then cash out initial charge
        # against that same historical harvest counter.
        joules = math.floor(min(collected-source["given_j"],
                                source["charge_j"]-source["capacity_j"]*bank["reserve_fraction"]))
        if joules < 1:
            continue
        drawn = app.live.act({"session":app.live.session.id, "op":"draw", "store":source["id"], "joules":joules})
        measured = drawn.get("store") or {}
        if measured.get("id") != source["id"] or measured.get("given_j") is None or drawn.get("drawn") != joules:
            raise ValueError("Automatic banking requires an exact native debit receipt")
        pending.append({"request_id":"auto-"+uuid.uuid4().hex, "owner_id":bank["owner_id"],
                        "joules":joules, "store_name":source["name"], "store_id":source["id"],
                        "given_after_j":measured["given_j"]})
        bank["exported_j"] += joules
        changed = True
    return changed


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


def _deposit_saved(app: Any, request_id: str) -> bool:
    if request_id in getattr(app.room, "market_durable_pending", set()):
        return True
    # A checkpoint can already have settled and cleaned its paired receipt.
    with workshop_library._connect(app) as db:
        _schema(db)
        return db.execute("SELECT 1 FROM market_deposits WHERE request_id=?", (request_id,)).fetchone() is not None


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
            if not _deposit_saved(app, request_id):
                if (not keep_world(app, "retrying an energy bank save") or
                        not _deposit_saved(app, request_id)):
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
        if not _deposit_saved(app, request_id):
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
    # Consistent ordering with guidance and the unattended checkpoint thread.
    # A bank first excludes installation; read-only views already in world
    # access must not try to upgrade their reader gate to an exclusive one.
    access = world_access.gate(app).enter(exclusive=True) if body.get('action') == 'bank' else nullcontext()
    with access, world_access.state_lock(app), _lock:
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
                "automatic_sources": bank_sources(app, owner),
                "bankable": getattr(app, "live_holder", None) == "world" and app.live.session is not None,
                "guidance": _guidance(app, offers, balance), "orders": history,
                "pricing": "Base price rises by up to 75% as finite world stock is sold."}
