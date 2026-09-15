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
or put down there -- at rest, facing as it did when it went in.
"""
from __future__ import annotations

from typing import Any

import inventory
import room_world
import world_chat

# Where a thing is held when it comes out of the bag into the hand: out along the
# way the person faces and down from their eyes, about where a tool is held ready.
HOLD_OUT_M, HOLD_DOWN_M = 0.5, 0.35
# And where one is put down from the bag: further out, and let fall from there.
PUT_OUT_M, PUT_DOWN_M = 0.7, 0.9


def inventory_of(app: Any) -> inventory.Inventory:
    """The room's record, made from what the room kept (room_store) the first time."""
    room = app.room
    kept = getattr(room, "inventory", None)
    if not isinstance(kept, inventory.Inventory):
        kept = inventory.Inventory(getattr(room, "inventory_record", None))
        room.inventory = kept
    return kept


def _state(app: Any) -> dict[str, Any]:
    session = app.live.session
    return (session.state or {}) if session is not None else {}


def _body(app: Any, name: str | None) -> dict[str, Any] | None:
    return next((b for b in _state(app).get("bodies") or [] if b.get("name") == name), None)


def shown(app: Any) -> dict[str, Any]:
    """The record as the page shows it: each hand and the bag, by name."""
    record = inventory_of(app).record()
    names = {item["id"]: item["name"] for item in inventory.items_of(app.room.spec)}

    def named(item: str | None) -> dict[str, str] | None:
        return {"id": item, "name": names.get(item, item)} if item else None

    return {"record": record,
            "hands": {hand: named(item) for hand, item in record["hands"].items()},
            "stowed": [named(item) for item in record["stowed"]],
            # The hand the engine has: the only one that holds anything yet.
            "hand_in_the_world": record["dominant"]}


def after_open(app: Any, opened: dict[str, Any] | None = None) -> dict[str, Any]:
    """After the room is opened, or opened again because the chat changed it:
    put what the person has back where the record says.

    A room opens from its spec, so the bag's things open standing in the world:
    each is set aside again. A thing that was in a hand goes back into the bag,
    since the engine's hand is empty in a room just opened. A thing the room no
    longer has, or that cannot be set aside now (the chat joined it to
    something), leaves the record -- the record says only what is true of the
    room. Returns what the page shows."""
    record = inventory_of(app)
    session = app.live.session
    if session is None:
        return shown(app)
    items = {item["id"]: item for item in inventory.items_of(app.room.spec)}
    changed = False
    for hand in inventory.HANDS:
        if record.hands[hand]:
            if record.hands[hand] not in record.stowed:
                record.stowed.append(record.hands[hand])
            record.hands[hand] = None
            changed = True
    present = {b.get("name") for b in (session.state or {}).get("bodies") or []}
    parked: set[str] = set()
    for item in list(record.stowed):
        thing = items.get(item)
        if thing is None or thing["installed"] or not thing["one_piece"]:
            record.stowed.remove(item)
            changed = True
            continue
        if thing["name"] not in present:
            continue
        try:
            app.live.act({"session": session.id, "op": "park", "name": thing["name"]})
            parked.add(thing["name"])
        except Exception:   # the engine would not set it aside: it stays in the world
            record.stowed.remove(item)
            changed = True
    if changed:
        record.revision += 1
    # The answer the page draws the room from was made before these were set
    # aside, and the engine's next replies will not say they went -- a whole
    # reply leaves it nothing to compare with -- so they are taken out of it
    # here, and the page never draws them.
    if isinstance(opened, dict) and parked:
        opened["bodies"] = [b for b in opened.get("bodies") or [] if b.get("name") not in parked]
    return shown(app)


def request(app: Any, body: Any) -> dict[str, Any]:
    """One change to what the person has (POST /api/world/inventory).

    The body carries:
    - request: its own id;
    - revision: the record's revision the page last saw;
    - op: take, equip, stow or drop;
    - item: an id, or the name of any of its parts, which is what the page knows;
    - person: where they are.

    The answer is the record's (inventory.Inventory.request) with the room's part,
    and what the page shows now."""
    if not isinstance(body, dict):
        raise ValueError("expected {request, revision, op, item, person}")
    request_id = str(body.get("request") or "")
    if not request_id:
        raise ValueError("a change needs its own request id, so a retry is not done twice")
    record = inventory_of(app)
    items = inventory.items_of(app.room.spec)
    op = str(body.get("op") or "")
    asked = str(body.get("item") or "")
    thing = next((i for i in items if i["id"] == asked), None) or \
        next((i for i in items if asked in i["bodies"]), None)
    item = thing["id"] if thing else asked
    name = thing["name"] if thing else None
    live = _body(app, name)
    kg = float(live["mass_kg"]) if live and live.get("mass_kg") is not None else None
    person = world_chat.where_the_person_is(body.get("person"))

    def act(plan: dict[str, Any]) -> dict[str, Any]:
        session = app.live.session
        if session is None:
            raise ValueError("the room is not open")
        sid = session.id
        holding = ((session.state or {}).get("hand") or {}).get("holding") or ""
        if plan["to"] == "stowed":
            if holding == name:
                app.live.act({"session": sid, "op": "release"})
            now = _body(app, name)
            if now and now.get("orientation_wxyz"):
                record.facing[item] = [float(v) for v in now["orientation_wxyz"]]
            app.live.act({"session": sid, "op": "park", "name": name})
            return {"set_aside": name}
        if plan["from"] == "stowed":
            if person is None or not person.get("eyes_m"):
                raise ValueError("the page did not say where you are")
            eyes, (fx, _, fz) = person["eyes_m"], person["facing"]
            into_hand = plan["to"] in inventory.HANDS
            out, down = (HOLD_OUT_M, HOLD_DOWN_M) if into_hand else (PUT_OUT_M, PUT_DOWN_M)
            at = [round(eyes[0] + fx * out, 4), round(eyes[1] - down, 4), round(eyes[2] + fz * out, 4)]
            app.live.act({"session": sid, "op": "unpark", "name": name, "at": at,
                          "q": record.facing.get(item, [1.0, 0.0, 0.0, 0.0])})
            if into_hand:
                app.live.act({"session": sid, "op": "wield", "name": name, "grip": at})
            return {"brought_back": name, "at_m": at, "held": into_hand}
        if plan["from"] in inventory.HANDS and plan["to"] == "world":
            if holding == name:
                app.live.act({"session": sid, "op": "release"})
            return {"let_go": name}
        raise ValueError("that is not something the room can do yet")

    # One hand in the engine: a thing taken into a hand goes to the dominant one,
    # and into the bag when that hand is full.
    hand = record.dominant if op in ("equip", "take_up") else body.get("hand")
    answer = record.request(request_id, body.get("revision"), op, item, items, act, hand=hand,
                            kg=kg, lift_kg=room_world.banjo_mcp.HAND_LIFTS_KG)
    return dict(answer, shown=shown(app))
