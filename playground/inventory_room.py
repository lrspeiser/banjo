"""The room's side of what a person has. inventory.py is the record; this is what
taking, holding, stowing and putting down DO to the thing, with the engine's own
operations on the room the page has open:
- set aside (park);
- brought back (unpark);
- taken by the hand (wield);
- let go (release).

This first slice has one hand in the engine. What is shown in the dominant hand
is the thing the engine's hand holds, and a second thing goes into the bag rather
than into a hand that cannot hold it yet. Two hands come with the bow, increment
4 of the owner's spec.

A thing comes out of the bag where the person can see it: held in front of them,
or put down there -- at rest, facing as it did when it went in. A thing taken up
from the world is gripped where it lies, or where the page says its handle is.

A thing of several parts is taken up whole: the hand grips the part the person
pointed at, and the others come with it on the joints they already have -- which
stay joints, so a mace's head swings on its chain as it is carried. What it
weighs, for the lift, is every part's.

Where the hand takes hold is the thing's own GRIP point when it has one: the
interaction point its maker -- the Workshop's model, the room's chat, a recipe
-- put where a person's hand goes (hold_point). A mace is held by the end of its
handle whichever part was pointed at. And the part that does the work, what a
swing aims (use_point), is its USE point furthest from that grip: a mace's head.
"""
from __future__ import annotations

import math
from typing import Any

import inventory
import item_pictures
import live_session
import player_world
import room_world
import world_chat

# Where a thing is held when it comes out of the bag into the hand: out along the
# way the person faces and down from their eyes, about where a tool is held ready.
HOLD_OUT_M, HOLD_DOWN_M = 0.5, 0.35
# And where one is put down from the bag: further out, and let fall from there.
PUT_OUT_M, PUT_DOWN_M = 0.7, 0.9
# How far from a thing's middle a grip the page gives may be: a pick's handle is
# half a metre from its middle, and a grip further than this is not on it.
GRIP_REACH_M = 1.5
# A grip point this far from the middle of its part says where the hand goes.
# One at the middle -- which is where every body's point is when nobody placed
# one (interaction_points.checked) -- says nothing the middle does not already.
DECLARED_GRIP_M = 0.02


def inventory_of(app: Any, player_id: str = "") -> inventory.Inventory:
    """The room's record, made from what the room kept (room_store) the first time."""
    room = app.room
    if getattr(app, "world_id", None):
        profile = getattr(room, "player_records", {}).get(player_id)
        if profile is None:
            raise ValueError("Join this world before reading an inventory")
        live = getattr(room, "player_inventories", None)
        if live is None:
            live = room.player_inventories = {}
        if player_id not in live:
            live[player_id] = inventory.Inventory(profile.get("inventory"))
        return live[player_id]
    kept = getattr(room, "inventory", None)
    if not isinstance(kept, inventory.Inventory):
        kept = inventory.Inventory(getattr(room, "inventory_record", None))
        room.inventory = kept
    return kept


def _state(app: Any) -> dict[str, Any]:
    session = getattr(getattr(app, "live", None), "session", None)
    return (session.state or {}) if session is not None else {}


def _hand_of(app: Any, player_id: str = "") -> dict[str, Any]:
    state = _state(app)
    if player_id:
        return (state.get("player_hands") or {}).get(player_id) or {}
    return state.get("hand") or ({"holding": state["held"]} if "held" in state else {})


def items_of(app: Any) -> list[dict[str, Any]]:
    """Physical connected components, including retained failed-joint history.

    The authored graph is a fallback before a native graph has been received.
    A native empty graph is authoritative too.
    """
    return inventory.items_of(app.room.spec, _state(app).get("joints"))


def reconcile(app: Any, *, released: bool = True) -> None:
    """A separated held assembly owns only what the native grip still carries.

    Rebind the retained component's bag slot/facing without moving bodies or
    deleting accepted request answers. Released components remain in the world.
    Stored assemblies cannot acquire new failures while native-parked; their
    already reconciled component ids persist normally through reopening.
    """
    current = items_of(app)
    by_body = {name: item for item in current for name in item["bodies"]}
    authored = inventory.items_of(app.room.spec)
    original = {item["id"]: item for item in authored}
    players = list(player_world.records(app)) if getattr(app, "world_id", None) else [""]
    for actor in players:
        record = inventory_of(app, actor)
        native_hand = _hand_of(app, actor)
        holding = str(native_hand.get("holding") or "")
        with record.lock:
            old_id = record.hands.get(record.dominant)
            # An authoritative native release leaves the item in the world,
            # not in a phantom inventory hand. Missing hand data is not a release.
            if released and old_id and "holding" in native_hand and not holding:
                record.forget(old_id)
                record.revision += 1
                continue
            old = original.get(old_id)
            if not old or not any(i.get("separated_from") == old_id for i in current):
                continue
            retained = by_body.get(holding) if holding in old["bodies"] else None
            new_id = retained["id"] if retained else None
            bindings = getattr(record, "_held_components", {})
            names = tuple(retained["bodies"]) if retained else ()
            if new_id == old_id and bindings.get(old_id) == names:
                continue
            record.hands[record.dominant] = new_id
            slot = record.home.pop(old_id, None)
            if slot is not None and new_id:
                record.home[new_id] = slot
            facing = record.facing.pop(old_id, None)
            if facing is not None and new_id:
                record.facing[new_id] = facing
            if new_id:
                bindings[new_id] = names
            record._held_components = bindings
            record.revision += 1


def _body(app: Any, name: str | None) -> dict[str, Any] | None:
    return next((b for b in _state(app).get("bodies") or [] if b.get("name") == name), None)


def whole_kg(app: Any, thing: dict[str, Any] | None) -> float | None:
    """What all of a thing weighs, as the running room has it: every body wearing
    the name of any of its parts. None when none of it is in the world (in the
    bag, or not a thing of the room's)."""
    if thing is None:
        return None
    parts = set(thing["bodies"])
    masses = [float(b["mass_kg"]) for b in _state(app).get("bodies") or []
              if b.get("name") in parts and b.get("mass_kg") is not None]
    return sum(masses) if masses else None


def item_holding(app: Any, part: str | None) -> dict[str, Any] | None:
    """The room's item a body is part of, or None."""
    if not part:
        return None
    return next((i for i in items_of(app) if part in i["bodies"]), None)


def _turned(q: list[float], v: list[float]) -> list[float]:
    w, x, y, z = (float(c) for c in q)
    return [(1-2*(y*y+z*z))*v[0]+2*(x*y-w*z)*v[1]+2*(x*z+w*y)*v[2],
            2*(x*y+w*z)*v[0]+(1-2*(x*x+z*z))*v[1]+2*(y*z-w*x)*v[2],
            2*(x*z-w*y)*v[0]+2*(y*z+w*x)*v[1]+(1-2*(x*x+y*y))*v[2]]


def _points(app: Any, names: list[str], kind: str) -> list[tuple[str, list[float], list[float]]]:
    """Every interaction point of a kind on these bodies, as the running room
    has them: (body, its offset from the body's middle, where it is now). Points
    are body-local metres from the centre of mass (mcp/interaction_points.py)."""
    live = {b["name"]: b for b in _state(app).get("bodies") or []
            if b.get("name") in names and b.get("position_m")}
    out = []
    for record in app.room.spec.get("interaction_points") or []:
        body = live.get(record.get("body")) if isinstance(record, dict) else None
        if body is None:
            continue
        for point in record.get("points") or []:
            if point.get("kind") != kind:
                continue
            local = [float(v) for v in point.get("position_m") or [0.0, 0.0, 0.0]]
            turned = _turned(body.get("orientation_wxyz") or [1.0, 0.0, 0.0, 0.0], local)
            out.append((body["name"], local,
                        [float(body["position_m"][k]) + turned[k] for k in range(3)]))
    return out


def hold_point(app: Any, thing: dict[str, Any] | None, pointed: str) -> tuple[str, list[float] | None]:
    """Which part the hand takes a thing by, and where on it (None: its middle).

    The thing's own grip, where its maker put one: a grip point away from the
    middle of its part -- on the part pointed at when it has one, else the
    first. Failing that, a thing of several parts is taken by the part its Use
    works (the body whose primary action is a real one, not the Inspect every
    part gets by default), and anything else by the part pointed at."""
    names = list(thing["bodies"]) if thing else [pointed]
    placed = [(name, at) for name, local, at in _points(app, names, "grip")
              if math.hypot(*local) > DECLARED_GRIP_M]
    if placed:
        return next(((n, at) for n, at in placed if n == pointed), placed[0])
    if len(names) > 1:
        from mcp import core_use
        worked = next((a.get("body") for a in app.room.spec.get("actions") or []
                       if isinstance(a, dict) and a.get("body") in names and a.get("primary")
                       and a.get("steps") != core_use.DEFAULT["steps"]), None)
        if worked and _body(app, worked) is not None:
            return worked, None
    return pointed, None


def use_point(app: Any, thing: dict[str, Any] | None, grip: list[float], held: str) -> list[float] | None:
    """Where the part of a thing that does its work is now: the use point
    furthest from where the hand grips it -- a mace's head, a hammer's face.
    A room gives every body a use point at its middle when nobody placed one,
    so a plain block's is its middle. None only when no part has one at all."""
    names = list(thing["bodies"]) if thing else [held]
    uses = _points(app, names, "use")
    if not uses:
        return None
    return max(uses, key=lambda u: math.dist(u[2], grip))[2]


def _carried(app: Any, player_id: str = "") -> Any:
    """What the person carries, as the engine counts it -- with ALL of a thing of
    several parts in the hand, not only the part the hand grips. The engine
    counts active ordinary fixed assemblies. Other profile parts remain a host
    carrying estimate; these are not added again when native mass includes them."""
    state = _state(app)
    carried = live_session.current_carried(app.live.session,player_id)
    held = str(_hand_of(app, player_id).get("holding") or "")
    if player_id and isinstance(carried, dict):
        # Native ground and parked bodies belong to this player. Add only the
        # extra parts of a jointed held item beyond the native gripped body.
        thing = item_holding(app, held) if held else None
        own_kg = whole_kg(app, thing) if thing else 0.0
        gripped = (float(carried['held_objects_kg']) if 'held_objects_kg' in carried else
            sum(float(b.get('mass_kg') or 0.0) for b in state.get('bodies') or [] if b.get('name')==held))
        own_kg = float(carried.get('objects_kg') or 0.0) + max(0.,float(own_kg or 0.)-gripped)
        ground_kg = sum(float(carried.get(k) or 0.0) for k in ("sand_kg", "soil_kg", "rock_kg"))
        total = ground_kg + own_kg
        limit = float(carried.get("limit_kg") or 0.0)
        return dict(carried, objects_kg=own_kg, total_kg=total,
                    available_kg=max(0.0, limit-total), over_limit_kg=max(0.0, total-limit))
    thing = item_holding(app, held) if held else None
    if not isinstance(carried, dict) or thing is None or len(thing["bodies"]) < 2:
        return carried
    whole = whole_kg(app, thing)
    gripped = (float(carried['held_objects_kg']) if 'held_objects_kg' in carried else
        sum(float(b["mass_kg"]) for b in state.get("bodies") or []
            if b.get("name") == held and b.get("mass_kg") is not None))
    if whole is None:
        return carried
    rest = max(0.0, whole - gripped)
    return dict(carried, **{key: float(carried[key]) + rest for key in ("objects_kg", "total_kg")
                            if isinstance(carried.get(key), (int, float))})


def _grip(asked: Any, now: dict[str, Any]) -> list[float]:
    """Where the hand takes hold of a thing it takes up: where the page says --
    a tool by its handle -- or, said nowhere, its middle where it is now."""
    middle = [float(v) for v in now["position_m"]]
    if asked is None:
        return [round(v, 4) for v in middle]
    if not isinstance(asked, (list, tuple)) or len(asked) != 3:
        raise ValueError("a grip is three numbers, metres")
    grip = [float(v) for v in asked]
    if not all(math.isfinite(v) for v in grip):
        raise ValueError("a grip is three numbers, metres")
    if math.dist(grip, middle) > GRIP_REACH_M:
        raise ValueError(f"that grip is not on it: {math.dist(grip, middle):.1f} m from its middle")
    return [round(v, 4) for v in grip]


def shown(app: Any, player_id: str = "") -> dict[str, Any]:
    """The record as the page shows it: each hand and the bag's slots, by name,
    with what each thing is made of and its shape. An empty slot is None, so the
    page numbers the slots as the record does; a thing in a hand carries the slot
    kept for it (`slot`), which its number puts it back into."""
    reconcile(app)
    record = inventory_of(app, player_id).record()
    spec = app.room.spec
    bodies = {str(b["name"]): b for b in spec.get("bodies") or [] if isinstance(b, dict) and b.get("name")}
    items = {item["id"]: item for item in items_of(app)}

    def named(item: str | None, slot: int | None = None) -> dict[str, Any] | None:
        if not item:
            return None
        thing = items.get(item)
        first = bodies.get(thing["name"]) if thing else None
        out: dict[str, Any] = {"id": item, "name": thing["name"] if thing else item}
        if thing:
            import product_labels
            out.update(product_labels.for_item(app,thing))
        if first:
            out["material"] = str(first.get("material") or "")
            out["shape"] = str(first.get("shape") or "box")
        if slot is not None:
            out["slot"] = slot
        # Which kept picture of it there is (item_pictures): its revision
        # only, so the page fetches the picture itself once, not every poll.
        picture = item_pictures.revision_of(app, item)
        if picture:
            out["thumbnail_rev"] = picture
        # A thing of several parts says which, so the page counts every one of
        # them as held -- the hand grips one, and the part it grips need not be
        # the one the thing is named after.
        if thing and len(thing["bodies"]) > 1:
            out["parts"] = list(thing["bodies"])
        return out

    import product_labels
    return {"record": record, "carried": _carried(app,player_id),
            "labels":product_labels.body_labels(app),
            "hands": {hand: named(item, record["home"].get(item)) for hand, item in record["hands"].items()},
            "stowed": [named(item) for item in record["stowed"]],
            # The hand the engine has: the only one that holds anything yet.
            "hand_in_the_world": record["dominant"]}


def after_open(app: Any, opened: dict[str, Any] | None = None,
               player_id: str = "") -> dict[str, Any]:
    """After the room is opened, or opened again because the chat changed it:
    put what the person has back where the record says.

    A room opened from its spec has the bag's things standing in the world: each
    is set aside again. A thing that was in a hand goes back into the bag, into
    the slot kept for it, since the engine's hand is empty in a room just opened
    -- unless the room was opened again as it stood (a restart: live_session
    Live.open with a snapshot) and the engine's hand still holds it, when it
    stays in the hand. And there the record is what the person has: one of the
    room's things the engine holds and the record has in no hand is let go, and
    a thing the saved world had set aside but the record has out in the world is
    brought back where it was put away. A thing the room no longer has, or that
    cannot be set aside now (the chat fixed it to the room), leaves the record
    -- the record says only what is true of the room. Returns what the page
    shows."""
    if getattr(app, "world_id", None):
        return _after_open_players(app, opened, player_id)
    record = inventory_of(app)
    session = app.live.session
    if session is None:
        return shown(app)
    restored = opened.get("restored") if isinstance(opened, dict) else None
    whole = isinstance(restored, dict) and restored.get("tier") in ("whole", "carried")
    reconcile(app, released=whole)  # A fresh authored room moves old hands to the bag.
    items = {item["id"]: item for item in items_of(app)}
    item_of_body = {name: item_id for item_id, item in items.items() for name in item["bodies"]}
    state = session.state or {}
    # What the engine's hand holds as the room opens: nothing in a room opened
    # from its spec; what it held, in one opened again as it stood.
    holding = str((state.get("hand") or {}).get("holding") or "")
    # Opened again as it stood: whole after a restart, or carried into a room
    # the chat or an action has changed -- where the engine's hand still holds
    # what it held when that came back as it was, and what was set aside is
    # still away.
    parked: set[str] = set()
    with record.lock:
        changed = False
        for hand in inventory.HANDS:
            thing = items.get(record.hands.get(hand) or "")
            if whole and thing is not None and hand == record.dominant and holding in thing["bodies"]:
                continue
            changed = record.back_to_bag(hand) or changed
        held = item_of_body.get(holding)
        if whole and held is not None and held not in record.hands.values():
            try:
                app.live.act({"session": session.id, "op": "release"})
            except Exception:   # nothing to let go of after all
                pass
        present = {b.get("name") for b in (session.state or {}).get("bodies") or []}
        for item in [i for i in record.stowed if i]:
            thing = items.get(item)
            if thing is None or thing["installed"]:
                record.forget(item)
                changed = True
                continue
            if thing["name"] not in present:
                continue
            try:
                app.live.act({"session": session.id, "op": "park", "name": thing["name"]})
                parked.add(thing["name"])
            except Exception:   # the engine would not set it aside: it stays in the world
                record.forget(item)
                changed = True
        if whole:
            # Every part of what is in the bag: a thing of parts on joints was
            # set aside whole, and asking for one of its parts back would bring
            # all of it out of the bag.
            in_bag = {name for i in record.stowed if i and i in items for name in items[i]["bodies"]}
            for away in restored.get("parked") or []:
                name = away.get("name") if isinstance(away, dict) else None
                if not name or name in in_bag:
                    continue
                try:
                    app.live.act({"session": session.id, "op": "unpark", "name": name,
                                  "at": away["at_m"], "q": away["facing_wxyz"]})
                except Exception:   # it stays set aside
                    pass
        if changed:
            record.revision += 1
    # The answer the page draws the room from was made before these were set
    # aside, and the engine's next replies will not say they went -- a whole
    # reply leaves it nothing to compare with -- so they are taken out of it
    # here, and the page never draws them.
    if isinstance(opened, dict) and parked:
        opened["bodies"] = [b for b in opened.get("bodies") or [] if b.get("name") not in parked]
    return shown(app)


def _after_open_players(app: Any, opened: dict[str, Any] | None,
                        player_id: str) -> dict[str, Any]:
    """Reconcile every guest's bag with one restored native room."""
    with player_world.lock_of(app):
        players = player_world.records(app)
        if not players:
            raise ValueError("Join this world before opening its room")
        session = app.live.session
        if session is None:
            return shown(app, player_id or next(iter(players)))
        items = {item["id"]: item for item in items_of(app)}
        # Worlds saved before per-player native hands kept one legacy hand and
        # its owner in the room record. Transfer that live hold once, instead
        # of filing the owner's item in a bag while the legacy hand keeps it.
        legacy = (session.state or {}).get("hand") or {}
        legacy_name = str(legacy.get("holding") or "")
        if legacy_name:
            owner = getattr(app.room, "hand_owner", None)
            if owner not in players:
                matches = [ident for ident in players
                           if any(legacy_name in items[item]["bodies"]
                                  for item in inventory_of(app, ident).hands.values() if item in items)]
                owner = matches[0] if len(matches) == 1 else None
            app.live.act({"session": session.id, "op": "release"})
            if owner:
                if legacy.get("mode") == "grip":
                    app.live.act({"session": session.id, "op": "wield", "actor": owner,
                                  "name": legacy_name, "grip": legacy.get("grip_m")})
                else:
                    app.live.act({"session": session.id, "op": "grab", "actor": owner,
                                  "name": legacy_name})
                target = legacy.get("target_m")
                if isinstance(target, list) and len(target) == 3:
                    app.live.act({"session": session.id, "op": "move", "actor": owner,
                                  "to": target})
        restored = opened.get("restored") if isinstance(opened, dict) else None
        whole = isinstance(restored, dict) and restored.get("tier") in ("whole", "carried")
        reconcile(app, released=whole)
        native_hands = (session.state or {}).get("player_hands") or {}
        parked: set[str] = set()
        for ident in players:
            record = inventory_of(app, ident)
            holding = str((native_hands.get(ident) or {}).get("holding") or "")
            kept_hand = False
            with record.lock:
                changed = False
                for hand in inventory.HANDS:
                    item = record.hands.get(hand)
                    thing = items.get(item or "")
                    if (whole and thing is not None
                            and hand == record.dominant and holding in thing["bodies"]):
                        kept_hand = True
                        continue
                    changed = record.back_to_bag(hand) or changed
                for item in [i for i in record.stowed if i]:
                    thing = items.get(item)
                    if thing is None or thing["installed"]:
                        record.forget(item)
                        changed = True
                        continue
                if changed:
                    record.revision += 1
            if whole and holding and not kept_hand:
                held_item = next((item for item, thing in items.items()
                                  if holding in thing["bodies"]), None)
                if held_item is None or all(inventory_of(app, other).where(held_item) == "world"
                                            for other in players):
                    kept_hand = True
            if holding and not kept_hand:
                app.live.act({"session": session.id, "op": "release", "actor": ident})
        app.room.hand_owner = None
        present = {b.get("name") for b in (session.state or {}).get("bodies") or []}
        for ident in players:
            record = inventory_of(app, ident)
            for item in [i for i in record.stowed if i]:
                thing = items.get(item)
                if thing and thing["name"] in present:
                    try:
                        app.live.act({"session": session.id, "op": "park", "name": thing["name"],
                                      "actor": ident})
                        parked.update(thing["bodies"])
                    except Exception:
                        with record.lock:
                            record.forget(item)
                            record.revision += 1
        if whole:
            in_bags = {name for ident in players
                       for item in inventory_of(app, ident).stowed if item in items
                       for name in items[item]["bodies"]}
            for away in restored.get("parked") or []:
                name = away.get("name") if isinstance(away, dict) else None
                if name and name not in in_bags:
                    try:
                        app.live.act({"session": session.id, "op": "unpark", "name": name,
                                      "at": away["at_m"], "q": away["facing_wxyz"]})
                    except Exception:
                        pass
        if isinstance(opened, dict) and parked:
            opened["bodies"] = [b for b in opened.get("bodies") or []
                                if b.get("name") not in parked]
        return shown(app, player_id or next(iter(players)))


def request(app: Any, body: Any, player_id: str = "") -> dict[str, Any]:
    if getattr(app, "world_id", None):
        with player_world.lock_of(app):
            return _request(app, body, player_id)
    return _request(app, body, player_id)


def _request(app: Any, body: Any, player_id: str) -> dict[str, Any]:
    """One change to what the person has (POST /api/world/inventory).

    The body carries:
    - request: its own id;
    - revision: the record's revision the page last saw;
    - op: take, take_up, equip, stow or drop;
    - item: an id, or the name of any of its parts, which is what the page knows;
    - person: where they are;
    - grip (take_up, optional): where the hand takes hold, [x, y, z] metres on
      the thing -- a tool's handle; its middle when not given.

    The answer is the record's (inventory.Inventory.request) with the room's part,
    and what the page shows now."""
    if not isinstance(body, dict):
        raise ValueError("expected {request, revision, op, item, person}")
    request_id = str(body.get("request") or "")
    if not request_id:
        raise ValueError("a change needs its own request id, so a retry is not done twice")
    reconcile(app)
    record = inventory_of(app, player_id)
    items = items_of(app)
    op = str(body.get("op") or "")
    asked = str(body.get("item") or "")
    thing = next((i for i in items if i["id"] == asked), None) or \
        next((i for i in items if asked in i["bodies"]), None)
    item = thing["id"] if thing else asked
    if player_id and request_id not in record.answers:
        for other_id in player_world.records(app):
            if other_id != player_id and inventory_of(app, other_id).where(item) != "world":
                with record.lock:
                    refused = record._remember(request_id, {"ok": False,
                        "why": "That item belongs to another player", "record": record.record()})
                return dict(refused, shown=shown(app, player_id))
    name = thing["name"] if thing else None
    # The part the hand takes hold of: the one the person pointed at -- the page
    # asks by the name of the part under its sight -- or, asked for by id, the
    # thing's first part. For a thing that is one body the two are the same.
    part = asked if thing and asked in thing["bodies"] else name
    # What it weighs is all of it: every part comes up with the one gripped.
    kg = whole_kg(app, thing)
    person = world_chat.where_the_person_is(body.get("person"))

    def live(plan: dict[str, Any]) -> dict[str, Any]:
        return app.live.act({**plan, **({"actor": player_id} if player_id else {})})

    def act(plan: dict[str, Any]) -> dict[str, Any]:
        # MOVING A THING BETWEEN SLOTS CHANGES NOTHING IN THE ROOM. It is
        # already set aside; only the order of the bag changes. Everything
        # below is about a thing crossing between the room and the person,
        # and the first branch -- anything going `to: "stowed"` -- would try
        # to park a thing that is already parked, which the engine refuses.
        if plan.get("op") == "slot":
            return {"put_in_slot": plan["slot"]}
        session = app.live.session
        if session is None:
            raise ValueError("the room is not open")
        sid = session.id
        holding = _hand_of(app, player_id).get("holding") or ""
        if plan["to"] == "stowed":
            now = _body(app, name)
            # Native park checks all constraints before releasing the hand.
            # Releasing here first would leave a refused stow saying "held"
            # in the inventory while the actual object had already been dropped.
            live({"session": sid, "op": "park", "name": name})
            if now and now.get("orientation_wxyz"):
                record.facing[item] = [float(v) for v in now["orientation_wxyz"]]
            # Every part went: a thing of parts on joints is set aside whole
            # (LiveWorld::park), and the page stops drawing all of it.
            return {"set_aside": name, "parts": list(thing["bodies"]) if thing else [name]}
        if plan["from"] == "world" and plan["to"] in inventory.HANDS:
            # Taken up: the engine's hand grips it where it lies -- where the
            # page says (a tool by its handle), else by the thing's own grip
            # (hold_point), else by the part pointed at, the rest of it coming
            # on its own joints.
            by, at = (part, None) if body.get("grip") is not None else hold_point(app, thing, part)
            now = _body(app, by)
            if now is None or not now.get("position_m"):
                raise ValueError(f"{inventory.said_name(by or asked)} is not in the room to take up")
            grip = [round(v, 4) for v in at] if at is not None else _grip(body.get("grip"), now)
            live({"session": sid, "op": "wield", "name": by, "grip": grip})
            said = {"taken_up": name, "held": True, "grip_m": grip}
            if by != name:
                said["by"] = by
            return said
        if plan["from"] == "stowed":
            if person is None or not person.get("eyes_m"):
                raise ValueError("the page did not say where you are")
            eyes, (fx, _, fz) = person["eyes_m"], person["facing"]
            into_hand = plan["to"] in inventory.HANDS
            out, down = (HOLD_OUT_M, HOLD_DOWN_M) if into_hand else (PUT_OUT_M, PUT_DOWN_M)
            at = [round(eyes[0] + fx * out, 4), round(eyes[1] - down, 4), round(eyes[2] + fz * out, 4)]
            live({"session": sid, "op": "unpark", "name": name, "at": at,
                          "q": record.facing.get(item, [1.0, 0.0, 0.0, 0.0])})
            if into_hand:
                by, grip = hold_point(app, thing, part)
                now = _body(app, by)
                live({"session": sid, "op": "wield", "name": by,
                      "grip": [round(v,4) for v in grip] if grip is not None else _grip(None,now)})
            return {"brought_back": name, "at_m": at, "held": into_hand}
        if plan["from"] in inventory.HANDS and plan["to"] == "world":
            # Whichever of its parts the hand has: a mace taken up by its head
            # is let go of just the same.
            if holding and holding in (thing["bodies"] if thing else [name]):
                live({"session": sid, "op": "release"})
            return {"let_go": name}
        raise ValueError("that is not something the room can do yet")

    # One hand in the engine: a thing taken into a hand goes to the dominant one,
    # and into the bag when that hand is full.
    hand = record.dominant if op in ("equip", "take_up") else body.get("hand")
    # Which numbered slot to put it in, for `slot`. Nothing else reads it.
    asked_slot = body.get("slot")
    answer = record.request(request_id, body.get("revision"), op, item, items, act, hand=hand,
                            kg=kg, lift_kg=room_world.banjo_mcp.HAND_LIFTS_KG,
                            slot=int(asked_slot) if isinstance(asked_slot, (int, float)) else None)
    return dict(answer, shown=shown(app, player_id))
