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
  items;
- a thing with any part anchored, or joined through its joints to anything
  anchored, is INSTALLED -- a gate on its post -- and is operated, never taken.
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
    - bodies: every part;
    - installed: whether any part is anchored, directly or through its joints;
    - one_piece: whether the engine holds it as one body joined to nothing,
      which is what can be set aside as it is.
    """
    bodies = [b for b in (spec.get("bodies") or []) if isinstance(b, dict) and b.get("name")]
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
                      "one_piece": len(pieces) == 1 and not (set(names) & jointed)})
    return items


def said_name(name: str) -> str:
    return name[:1].upper() + name[1:]


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
        self.stowed: list[str] = []
        for item in record.get("stowed") or []:
            if item and str(item) not in self.stowed and str(item) not in self.hands.values():
                self.stowed.append(str(item))
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
                "hands": dict(self.hands), "stowed": list(self.stowed),
                "facing": {item: list(q) for item, q in self.facing.items()}}

    def where(self, item: str) -> str:
        """"world", "stowed", or the hand it is in."""
        if item in self.stowed:
            return "stowed"
        for hand in HANDS:
            if self.hands[hand] == item:
                return hand
        return "world"

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
        """
        known = {entry["id"]: entry for entry in items}
        thing = known.get(item)
        if thing is None:
            return {"ok": False, "why": "there is nothing like that here"}
        name, here = thing["name"], self.where(item)
        if op in ("take", "take_up"):
            if here != "world":
                return {"ok": False, "why": f"{said_name(name)} is already yours"}
            if thing["installed"]:
                return {"ok": False, "why": f"{said_name(name)} is fixed in place: it can be used "
                                            f"where it is, not taken"}
            if not thing["one_piece"]:
                return {"ok": False, "why": f"{said_name(name)} is joined to something, so it "
                                            f"cannot be carried off as it is"}
            if kg is not None and lift_kg is not None and kg > lift_kg:
                return {"ok": False, "why": f"{said_name(name)} weighs {kg:.0f} kg, more than the "
                                            f"{lift_kg:.0f} kg a person can lift"}
            free = self._free_hand(hand) if op == "take_up" else None
            if free:
                return {"ok": True, "op": op, "item": item, "name": name, "from": "world",
                        "to": free, "did": f"Took up {name} in your {free} hand."}
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
            self.stowed.remove(item)
        elif came in HANDS:
            self.hands[came] = None
        if goes == "stowed":
            self.stowed.append(item)
        elif goes in HANDS:
            self.hands[goes] = item

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
                return self._remember(request_id, {"ok": False, "why": plan["why"],
                                                   "record": self.record()})
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
