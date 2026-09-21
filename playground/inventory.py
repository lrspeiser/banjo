"""What a person has, and what their hands hold: the server's record of it.

The owner's spec is docs/inventory-and-hands.md, and the design is
docs/inventory-and-hands-design.md. The page shows this record and never decides
it; the chat and the API get the same answers. What happens to the thing itself
-- set aside, brought into a hand, put down -- is the engine's (LiveWorld park and
unpark, and the hand), done by the room when a change is accepted here. Nothing
here changes unless that part was done.

Items are worked out from the room's spec each time, never kept twice:
- every body of a join group is one piece, which the engine builds as one body
  named after its first part;
- bodies joined to each other are one thing, so a stool's legs are not five
  items -- and that holds for exact rigid parts (precise_rigid_bodies) too;
- a thing with any part anchored, or joined through its joints to anything
  anchored, is INSTALLED -- a gate on its post -- and is operated, never taken.

Taken up, a thing is taken WHOLE (the owner, 2026-09-21: "when a user picks up
something it can be for the entire product so that it doesn't break, but needs
to still allow movement if part of the product, like swinging a mace"). The
hand takes hold of one part and the rest comes with it on its own joints, which
stay joints: a mace's head still swings on its chain, a wheel still turns. The
bag is narrower: the engine sets aside one body joined to nothing, so a thing
of joined parts can be carried in a hand but not stowed yet.

The bag is slots, numbered as the page's number keys number them: a thing keeps
the slot it went into, a thing taken out of one into a hand keeps that slot for
as long as it is held, and stowed again it goes back there -- so the number that
took it out is the number that puts it back.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

HANDS = ("right", "left")
# How many answers are remembered, so a request sent again -- a retry after a
# dropped connection -- is answered as it was the first time, and done once.
MAX_ANSWERS = 64


def items_of(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The room's things, as a person would count them.

    Each item is:
    - id: the smallest id of its bodies;
    - name: its first part's name, which is also the engine's name for a join
      group's piece;
    - bodies: every part, which is what a hand carries when it takes the thing
      up by any one of them;
    - installed: whether any part is anchored, directly or through its joints;
    - one_piece: whether the engine holds it as one body joined to nothing,
      which is what can be set aside as it is. An exact rigid part never is:
      the engine does not set those aside (LiveWorld park).
    """
    bodies = [b for b in (spec.get("bodies") or []) if isinstance(b, dict) and b.get("name")]
    # Exact rigid parts are the room's things as much as cell bodies are, and
    # are joined to each other the same way (a cart's wheels on their bearings).
    exact = [b for b in (spec.get("precise_rigid_bodies") or []) if isinstance(b, dict) and b.get("name")]
    exact_names = {str(b["name"]) for b in exact}
    bodies = bodies + exact
    parent = {str(b["name"]): str(b["name"]) for b in bodies}

    def root(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(a: str, b: str) -> None:
        if a in parent and b in parent and root(a) != root(b):
            parent[root(b)] = root(a)

    first_of_join: dict[str, str] = {}
    for body in bodies:
        join = str(body.get("join") or "")
        if join:
            union(first_of_join.setdefault(join, str(body["name"])), str(body["name"]))
    jointed: set[str] = set()
    for joint in spec.get("joints") or []:
        if isinstance(joint, dict):
            a, b = str(joint.get("a", "")), str(joint.get("b", ""))
            union(a, b)
            jointed.update(n for n in (a, b) if n in parent)
    groups: dict[str, list[dict[str, Any]]] = {}
    for body in bodies:
        groups.setdefault(root(str(body["name"])), []).append(body)
    items = []
    for members in groups.values():
        names = [str(b["name"]) for b in members]
        ids = sorted(str(b["id"]) for b in members if b.get("id"))
        pieces = {str(b.get("join") or "") or str(b["name"]) for b in members}
        items.append({"id": ids[0] if ids else names[0], "name": names[0], "bodies": names,
                      "installed": any(bool(b.get("anchored")) for b in members),
                      "one_piece": len(pieces) == 1 and not (set(names) & (jointed | exact_names))})
    return items


def said_name(name: str) -> str:
    return name[:1].upper() + name[1:]


def not_for_the_bag(thing: dict[str, Any]) -> str:
    """Why a thing that can be carried cannot be stowed yet, in words."""
    if len(thing["bodies"]) > 1:
        return "its parts are joined, and the bag only holds things of one piece"
    return "the bag cannot hold a thing like it yet"


class Inventory:
    """The record, and the only way it changes.

    A change is a request with its own id, made against the revision the asker
    last saw:
    - the same request twice is answered the same, and done once;
    - a request made against a revision that has moved on is refused, with the
      record as it is now;
    - an item is only ever in one place: in the world, stowed, or in one hand.
    """

    def __init__(self, record: dict[str, Any] | None = None) -> None:
        record = record if isinstance(record, dict) else {}
        self.lock = threading.Lock()
        self.revision = int(record.get("revision", 0) or 0)
        self.dominant = record.get("dominant") if record.get("dominant") in HANDS else "right"
        hands = record.get("hands") if isinstance(record.get("hands"), dict) else {}
        self.hands: dict[str, str | None] = {h: (str(hands[h]) if hands.get(h) else None) for h in HANDS}
        # The bag's slots in order: an item, or None for an empty slot. A record
        # kept before there were slots has no gaps in it, and reads the same.
        self.stowed: list[str | None] = []
        for item in record.get("stowed") or []:
            keep = bool(item) and str(item) not in self.stowed and str(item) not in self.hands.values()
            self.stowed.append(str(item) if keep else None)
        self._trim()
        # The slot each thing in a hand came out of, kept for it while it is
        # held, so stowing it puts it back there.
        home = record.get("home") if isinstance(record.get("home"), dict) else {}
        held = {item for item in self.hands.values() if item}
        self.home: dict[str, int] = {
            str(item): slot for item, slot in home.items()
            if str(item) in held and isinstance(slot, int) and not isinstance(slot, bool) and 0 <= slot < 1000}
        # Which way each thing faced as it went into the bag (w, x, y, z), so it
        # comes back out facing the same way: a cup upright, not as it was built.
        facing = record.get("facing") if isinstance(record.get("facing"), dict) else {}
        self.facing: dict[str, list[float]] = {
            str(item): [float(v) for v in q] for item, q in facing.items()
            if isinstance(q, (list, tuple)) and len(q) == 4}
        self.answers: dict[str, dict[str, Any]] = {}

    def record(self) -> dict[str, Any]:
        """The record as it is kept (room_store) and shown (the page)."""
        return {"revision": self.revision, "dominant": self.dominant,
                "hands": dict(self.hands), "stowed": list(self.stowed), "home": dict(self.home),
                "facing": {item: list(q) for item, q in self.facing.items()}}

    def where(self, item: str) -> str:
        """"world", "stowed", or the hand it is in."""
        if item in self.stowed:
            return "stowed"
        for hand in HANDS:
            if self.hands[hand] == item:
                return hand
        return "world"

    def slot_of(self, item: str) -> int | None:
        """The bag's slot a thing is in, or, while a hand holds it, the one kept
        for it."""
        return self.stowed.index(item) if item in self.stowed else self.home.get(item)

    def _trim(self) -> None:
        while self.stowed and self.stowed[-1] is None:
            self.stowed.pop()

    def _stow(self, item: str) -> None:
        """Into the bag: back into the slot kept for it when that is free, or
        else the first slot that is neither filled nor kept for another thing."""
        slot = self.home.pop(item, None)
        kept = set(self.home.values())

        def free(i: int) -> bool:
            return (i >= len(self.stowed) or self.stowed[i] is None) and i not in kept

        if slot is None or not free(slot):
            slot = next(i for i in range(len(self.stowed) + len(kept) + 1) if free(i))
        self.stowed.extend([None] * (slot + 1 - len(self.stowed)))
        self.stowed[slot] = item

    def _unstow(self, item: str) -> int:
        slot = self.stowed.index(item)
        self.stowed[slot] = None
        self._trim()
        return slot

    def back_to_bag(self, hand: str) -> bool:
        """What a hand holds, back into the bag, into the slot kept for it: a room
        just opened has nothing in the engine's hand. Whether there was anything."""
        item = self.hands.get(hand)
        if not item:
            return False
        self.hands[hand] = None
        if item in self.stowed:
            self.home.pop(item, None)
        else:
            self._stow(item)
        return True

    def forget(self, item: str) -> None:
        """Out of the record: the thing is in the world, because the room no
        longer has it as an item or it could not be set aside."""
        if item in self.stowed:
            self._unstow(item)
        for hand in HANDS:
            if self.hands[hand] == item:
                self.hands[hand] = None
        self.home.pop(item, None)

    def _free_hand(self, asked: str | None) -> str | None:
        if asked in HANDS:
            return asked if self.hands[asked] is None else None
        other = HANDS[1] if self.dominant == HANDS[0] else HANDS[0]
        for hand in (self.dominant, other):
            if self.hands[hand] is None:
                return hand
        return None

    def plan(self, op: str, item: str, items: list[dict[str, Any]], hand: str | None = None,
             kg: float | None = None, lift_kg: float | None = None) -> dict[str, Any]:
        """What `op` on `item` would do, or why not, in words -- without doing it.

        The ops are:
        - take: from the world into the inventory;
        - take_up: into a free hand, and into the inventory when the hands are
          full, since what is being used is never dropped or replaced;
        - equip: from the inventory into a hand;
        - stow: from a hand into the inventory;
        - drop: from a hand or the inventory into the world, in front of the
          person.

        A thing that is not one of the room's items -- a broken piece, which the
        room's spec does not have -- is refused as `unknown`, so the asker can
        tell it from a thing that is there and cannot be taken."""
        known = {entry["id"]: entry for entry in items}
        thing = known.get(item)
        if thing is None:
            return {"ok": False, "why": "there is nothing like that here", "unknown": True}
        name, here = thing["name"], self.where(item)
        if op in ("take", "take_up"):
            if here != "world":
                return {"ok": False, "why": f"{said_name(name)} is already yours"}
            if thing["installed"]:
                return {"ok": False, "why": f"{said_name(name)} is fixed in place: it can be used "
                                            f"where it is, not taken"}
            # The whole of it: `kg` is every part's, since every part comes too.
            if kg is not None and lift_kg is not None and kg > lift_kg:
                return {"ok": False, "why": f"{said_name(name)} weighs {kg:.0f} kg, more than the "
                                            f"{lift_kg:.0f} kg a person can lift"}
            free = self._free_hand(hand) if op == "take_up" else None
            if free:
                return {"ok": True, "op": op, "item": item, "name": name, "from": "world",
                        "to": free, "did": f"Took up {name} in your {free} hand."}
            if not thing["one_piece"]:
                why = (f"your hands are full, and {name} cannot go in the bag: {not_for_the_bag(thing)}"
                       if op == "take_up" else
                       f"{said_name(name)} cannot go in the bag: {not_for_the_bag(thing)}. "
                       f"Take it up in your hand instead")
                return {"ok": False, "why": why}
            full = " -- your hands are full" if op == "take_up" else ""
            return {"ok": True, "op": op, "item": item, "name": name, "from": "world",
                    "to": "stowed", "did": f"{said_name(name)} added to inventory{full}."}
        if op == "equip":
            if here in HANDS:
                return {"ok": False, "why": f"{said_name(name)} is already in your {here} hand"}
            if here != "stowed":
                return {"ok": False, "why": f"{said_name(name)} is not in your inventory"}
            free = self._free_hand(hand)
            if free is None:
                why = (f"your {hand} hand holds something: stow it first" if hand in HANDS
                       else "both hands are full: stow what is in one first")
                return {"ok": False, "why": why}
            return {"ok": True, "op": op, "item": item, "name": name, "from": "stowed",
                    "to": free, "did": f"{said_name(name)} in your {free} hand."}
        if op == "stow":
            if here not in HANDS:
                return {"ok": False, "why": f"{said_name(name)} is not in your hand"}
            if not thing["one_piece"]:
                return {"ok": False, "why": f"{said_name(name)} cannot go in the bag: "
                                            f"{not_for_the_bag(thing)}. Put it down instead"}
            return {"ok": True, "op": op, "item": item, "name": name, "from": here,
                    "to": "stowed", "did": f"Stowed {name}."}
        if op == "drop":
            if here == "world":
                return {"ok": False, "why": f"{said_name(name)} is not yours to put down"}
            return {"ok": True, "op": op, "item": item, "name": name, "from": here,
                    "to": "world", "did": f"Put {name} down."}
        return {"ok": False, "why": f"there is no {op!r}: take, take_up, equip, stow or drop"}

    def _apply(self, plan: dict[str, Any]) -> None:
        item, came, goes = plan["item"], plan["from"], plan["to"]
        if came == "stowed":
            slot = self._unstow(item)
            if goes in HANDS:
                self.home[item] = slot
        elif came in HANDS:
            self.hands[came] = None
        if goes == "stowed":
            self._stow(item)
        elif goes in HANDS:
            self.hands[goes] = item
        else:
            self.home.pop(item, None)

    def request(self, request_id: str, expected_revision: int | None, op: str, item: str,
                items: list[dict[str, Any]], act: Callable[[dict[str, Any]], Any] | None = None,
                hand: str | None = None, kg: float | None = None,
                lift_kg: float | None = None) -> dict[str, Any]:
        """One change, done once.

        `act(plan)` is the room's part: it sets the thing aside, puts it in the
        hand or puts it down. It raises to refuse, and then nothing here
        changes."""
        with self.lock:
            if request_id in self.answers:
                return self.answers[request_id]
            if expected_revision is not None and int(expected_revision) != self.revision:
                answer = {"ok": False, "why": "the inventory changed since you last saw it",
                          "record": self.record()}
                return self._remember(request_id, answer)
            plan = self.plan(op, item, items, hand, kg, lift_kg)
            if not plan["ok"]:
                refused = {"ok": False, "why": plan["why"], "record": self.record()}
                if plan.get("unknown"):
                    refused["unknown"] = True
                return self._remember(request_id, refused)
            try:
                said = act(plan) if act is not None else None
            except Exception as refused:   # the room could not do it: nothing changes
                return self._remember(request_id, {"ok": False, "why": str(refused),
                                                   "record": self.record()})
            self._apply(plan)
            self.revision += 1
            answer = {"ok": True, "did": plan["did"], "op": op, "item": item, "to": plan["to"],
                      "record": self.record()}
            if said is not None:
                answer["room"] = said
            return self._remember(request_id, answer)

    def _remember(self, request_id: str, answer: dict[str, Any]) -> dict[str, Any]:
        self.answers[request_id] = answer
        while len(self.answers) > MAX_ANSWERS:
            self.answers.pop(next(iter(self.answers)))
        return answer
