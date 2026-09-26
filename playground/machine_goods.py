"""Raw materials into finished goods (docs/machine-world.md, "Raw materials
into finished goods"): the room's account of what is in the ground beyond
sand and soil, what has been dug out of it and where it lies, and how one
thing is made into another.

A room declares it in one block, `goods`, in words a person or a model can
write:

    "goods": {
      "deposits": [{"name": "copper vein", "substance": "copper ore",
                    "at_m": [x, z], "radius_m": 4, "grade": 0.3, "reserve_kg": 2000}],
      "stockpiles": [{"name": "smelter intake", "at_m": [x, z], "radius_m": 1.5,
                      "holds": {"copper ore": 12.0}, "rack": false}],
      "recipes": [{"name": "smelt copper", "in": {"copper ore": 1.0},
                   "out": {"copper": 0.3, "slag": 0.7},
                   "work_j_per_kg": 2000, "s_per_kg": 2.0}]
    }

A deposit is a patch of ground where a scoop brings up ore with the soil:
`grade` of what is dug, by mass, until `reserve_kg` is gone. A stockpile is
a heap of goods at a place: what a machine dumps there, by substance, and
what another takes from it; one marked `rack` is the Workshop's own, and what
lands on it goes onto the Workshop's goods rack, to build machines with. A
recipe is what a machine that processes makes of what it is given, per
kilogram in: what it takes, what comes out (by mass; what is missing from
the out side is lost as waste), the work it draws from the machine's battery
and the time it takes. Nothing here is copper's: a substance is a name, and
the room's recipes are the only chemistry there is.

The ledger lives in the room's spec, changed in place, so it is kept with the
room (room_store) and read back by every sense. The ground's own account --
the sand and soil a scoop moves, LiveWorld's carried and exported volumes --
is untouched: ore is the share of a scoop's mass that leaves the ground for
good, exported, as a material packet is.
"""
from __future__ import annotations

import math
from typing import Any, Callable

# How near a machine must be to a stockpile to put onto it or take from it,
# beyond the stockpile's own radius: a hopper tipped at its edge.
REACH_M = 2.0
# A heap made where nothing was: its radius, and how far off an existing one
# a dump still lands on it.
HEAP_RADIUS_M = 1.0
NAMES_MOST = 64


def _xz(v: Any) -> list[float]:
    return [float(v[0]), float(v[1])]


class Goods:
    """The room's goods as they stand, over the spec's own block (changed in
    place, never copied, so the room keeps it)."""

    def __init__(self, spec: dict[str, Any] | None, on_rack: Callable[[str, float], None] | None = None):
        self.spec = spec if isinstance(spec, dict) else {}
        block = self.spec.get("goods")
        if not isinstance(block, dict):
            block = {}
            if isinstance(spec, dict):
                spec["goods"] = block
        self.block = block
        for key in ("deposits", "stockpiles", "recipes"):
            if not isinstance(block.get(key), list):
                block[key] = []
        self.on_rack = on_rack

    # ---- what is declared ----------------------------------------------------
    @property
    def deposits(self) -> list[dict[str, Any]]:
        return self.block["deposits"]

    @property
    def stockpiles(self) -> list[dict[str, Any]]:
        return self.block["stockpiles"]

    @property
    def recipes(self) -> list[dict[str, Any]]:
        return self.block["recipes"]

    def recipe(self, name: str) -> dict[str, Any] | None:
        return next((r for r in self.recipes if r.get("name") == name), None)

    def substances(self) -> list[str]:
        names: list[str] = []
        for d in self.deposits:
            names.append(str(d.get("substance")))
        for s in self.stockpiles:
            names.extend(str(k) for k in (s.get("holds") or {}))
        for r in self.recipes:
            names.extend(str(k) for k in (r.get("in") or {}))
            names.extend(str(k) for k in (r.get("out") or {}))
        return sorted(set(n for n in names if n))

    # ---- the ground's ore ----------------------------------------------------
    def deposit_at(self, x: float, z: float) -> dict[str, Any] | None:
        """The deposit under a point, if any, with something left in it."""
        for d in self.deposits:
            at = _xz(d["at_m"])
            if math.hypot(x - at[0], z - at[1]) <= float(d.get("radius_m", 0.0)) and self.reserve_kg(d) > 0.0:
                return d
        return None

    @staticmethod
    def reserve_kg(deposit: dict[str, Any]) -> float:
        return max(0.0, float(deposit.get("reserve_kg", 0.0)) - float(deposit.get("taken_kg", 0.0)))

    def dug(self, x: float, z: float, kg: float) -> dict[str, float]:
        """What a scoop of `kg` at a point brings up besides soil: the deposit's
        substance at its grade, no more than is left. Books it as taken."""
        d = self.deposit_at(x, z)
        if d is None or kg <= 0.0:
            return {}
        ore = min(kg * float(d.get("grade", 0.0)), self.reserve_kg(d))
        if ore <= 0.0:
            return {}
        d["taken_kg"] = round(float(d.get("taken_kg", 0.0)) + ore, 6)
        return {str(d["substance"]): ore}

    # ---- stockpiles ------------------------------------------------------------
    def stockpile_near(self, x: float, z: float, reach_m: float = REACH_M,
                       named: str | None = None) -> dict[str, Any] | None:
        """The nearest stockpile within reach of a point (its radius plus the
        reach), or the one of that name if it is within reach."""
        best, best_d = None, math.inf
        for s in self.stockpiles:
            if named is not None and s.get("name") != named:
                continue
            at = _xz(s["at_m"])
            d = math.hypot(x - at[0], z - at[1]) - float(s.get("radius_m", HEAP_RADIUS_M))
            if d <= reach_m and d < best_d:
                best, best_d = s, d
        return best

    def by_name(self, name: str) -> dict[str, Any] | None:
        return next((s for s in self.stockpiles if s.get("name") == name), None)

    def put(self, x: float, z: float, goods: dict[str, float], named: str | None = None) -> dict[str, Any]:
        """Goods heaped at a point: onto the stockpile within reach (the named
        one, if a name is given and it is within reach), or a new heap there.
        What lands on the Workshop's rack goes on to the goods rack."""
        goods = {str(k): float(v) for k, v in goods.items() if float(v) > 0.0}
        if not goods:
            return {"put": {}, "onto": None}
        pile = self.stockpile_near(x, z, named=named) if named else self.stockpile_near(x, z)
        if pile is None:
            pile = {"name": self._heap_name(), "at_m": [round(x, 3), round(z, 3)], "radius_m": HEAP_RADIUS_M,
                    "holds": {}}
            self.stockpiles.append(pile)
        holds = pile.setdefault("holds", {})
        for k, v in goods.items():
            holds[k] = round(float(holds.get(k, 0.0)) + v, 6)
        if pile.get("rack") and self.on_rack is not None:
            for k, v in goods.items():
                self.on_rack(k, v)
        return {"put": goods, "onto": pile["name"]}

    def take(self, x: float, z: float, kg_most: float, substance: str | None = None,
             named: str | None = None) -> dict[str, Any]:
        """Goods taken off the stockpile within reach: one substance, or
        whatever is there, up to `kg_most` in all."""
        pile = self.stockpile_near(x, z, named=named) if named else self.stockpile_near(x, z)
        if pile is None:
            raise ValueError("there is no stockpile within reach" + (f" called {named!r}" if named else ""))
        holds = pile.setdefault("holds", {})
        taken: dict[str, float] = {}
        room = max(0.0, float(kg_most))
        for k in ([substance] if substance else list(holds)):
            have = float(holds.get(k, 0.0))
            if have <= 0.0 or room <= 0.0:
                continue
            got = min(have, room)
            holds[k] = round(have - got, 6)
            if holds[k] <= 0.0:
                holds.pop(k, None)
            taken[k] = got
            room -= got
        return {"took": taken, "from": pile["name"], "left": dict(holds)}

    def _heap_name(self) -> str:
        n = 1
        names = {s.get("name") for s in self.stockpiles}
        while f"heap {n}" in names:
            n += 1
        return f"heap {n}"

    # ---- making ----------------------------------------------------------------
    def convert(self, recipe_name: str, holds: dict[str, float], kg_most: float) -> dict[str, Any]:
        """One batch of a recipe out of what a machine holds: as much of the
        inputs as are there, up to `kg_most` of the first input, and what comes
        out of them. Takes the inputs out of `holds` and returns the outputs,
        the work and the time the batch costs; nothing, when an input is
        missing."""
        recipe = self.recipe(recipe_name)
        if recipe is None:
            raise ValueError(f"the room has no recipe called {recipe_name!r}; it has "
                             + (", ".join(repr(r.get("name")) for r in self.recipes) or "none"))
        ins = {str(k): float(v) for k, v in (recipe.get("in") or {}).items()}
        outs = {str(k): float(v) for k, v in (recipe.get("out") or {}).items()}
        if not ins:
            raise ValueError(f"the recipe {recipe_name!r} takes nothing in")
        # The batch: kilograms of the recipe's unit -- its inputs sum to one
        # unit's worth -- limited by the scarcest input and by kg_most.
        total_in = sum(ins.values())
        units = min(float(holds.get(k, 0.0)) / v for k, v in ins.items() if v > 0.0)
        units = min(units, max(0.0, float(kg_most)) / total_in)
        if units <= 1e-9:
            missing = [k for k, v in ins.items() if float(holds.get(k, 0.0)) < v * 1e-6]
            return {"made": {}, "used": {}, "units": 0.0, "work_j": 0.0, "took_s": 0.0,
                    "missing": missing or list(ins)}
        used = {k: v * units for k, v in ins.items()}
        for k, v in used.items():
            holds[k] = round(float(holds.get(k, 0.0)) - v, 6)
            if holds[k] <= 1e-9:
                holds.pop(k, None)
        made = {k: v * units for k, v in outs.items()}
        kg_in = total_in * units
        return {"made": made, "used": used, "units": units, "kg_in": kg_in,
                "work_j": kg_in * float(recipe.get("work_j_per_kg", 0.0)),
                "took_s": kg_in * float(recipe.get("s_per_kg", 0.0)),
                "waste_kg": max(0.0, kg_in - sum(made.values()))}

    # ---- for the senses ----------------------------------------------------------
    def reading(self, x: float, z: float) -> dict[str, Any]:
        """What is where, from a point: each deposit and stockpile with its
        distance, and the recipes the room knows."""
        def dist(at: Any) -> float:
            a = _xz(at)
            return round(math.hypot(x - a[0], z - a[1]), 2)
        return {
            "deposits": [{"name": d.get("name"), "substance": d.get("substance"), "x_m": d["at_m"][0],
                          "z_m": d["at_m"][1], "radius_m": d.get("radius_m"), "grade": d.get("grade"),
                          "left_kg": round(self.reserve_kg(d), 1), "distance_m": dist(d["at_m"])}
                         for d in self.deposits],
            "stockpiles": [{"name": s.get("name"), "x_m": s["at_m"][0], "z_m": s["at_m"][1],
                            "holds_kg": {k: round(float(v), 2) for k, v in (s.get("holds") or {}).items()},
                            "rack": bool(s.get("rack")), "distance_m": dist(s["at_m"]),
                            "within_reach": dist(s["at_m"]) <= float(s.get("radius_m", HEAP_RADIUS_M)) + REACH_M}
                           for s in self.stockpiles],
            "recipes": [{"name": r.get("name"), "in": r.get("in"), "out": r.get("out"),
                         "work_j_per_kg": r.get("work_j_per_kg"), "s_per_kg": r.get("s_per_kg")}
                        for r in self.recipes],
        }


# ---- the room's spelling, checked -------------------------------------------------

def checked(given: Any) -> dict[str, Any]:
    """The goods block as the room keeps it: checked, in the room's metres and
    kilograms. Raises with what is wrong."""
    if given is None:
        return {"deposits": [], "stockpiles": [], "recipes": []}
    if not isinstance(given, dict):
        raise ValueError("goods is an object: deposits, stockpiles, recipes")
    unknown = set(given) - {"deposits", "stockpiles", "recipes"}
    if unknown:
        raise ValueError(f"goods cannot say {sorted(unknown)}: it holds deposits, stockpiles and recipes")

    def number(v: Any, lo: float, hi: float, what: str) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{what} is a number") from None
        if not (lo <= f <= hi) or f != f:
            raise ValueError(f"{what} is between {lo:g} and {hi:g}")
        return f

    def name(v: Any, what: str) -> str:
        s = " ".join(str(v or "").split())[:NAMES_MOST]
        if not s:
            raise ValueError(f"{what} needs a name")
        return s

    def masses(v: Any, what: str, lo: float = 0.0) -> dict[str, float]:
        if not isinstance(v, dict) or len(v) > 16:
            raise ValueError(f"{what} is a map of at most 16 substances to kilograms")
        out = {}
        for k, kg in v.items():
            out[name(k, f"{what}'s substance")] = number(kg, lo, 1e9, f"{what} {k}")
        return out

    out: dict[str, Any] = {"deposits": [], "stockpiles": [], "recipes": []}
    names: set[str] = set()
    for i, d in enumerate(given.get("deposits") or []):
        if not isinstance(d, dict):
            raise ValueError(f"deposit {i} is an object")
        n = name(d.get("name") or f"deposit {i + 1}", f"deposit {i}")
        if n in names:
            raise ValueError(f"two things in goods are called {n!r}")
        names.add(n)
        if not isinstance(d.get("at_m"), (list, tuple)) or len(d["at_m"]) != 2:
            raise ValueError(f"deposit {n!r} at_m is [x, z] in metres")
        made = {"name": n, "substance": name(d.get("substance"), f"deposit {n!r} substance"),
                "at_m": [number(d["at_m"][0], -1000.0, 1000.0, f"deposit {n!r} x"),
                         number(d["at_m"][1], -1000.0, 1000.0, f"deposit {n!r} z")],
                "radius_m": number(d.get("radius_m", 3.0), 0.5, 200.0, f"deposit {n!r} radius_m"),
                "grade": number(d.get("grade", 0.1), 0.001, 1.0, f"deposit {n!r} grade"),
                "reserve_kg": number(d.get("reserve_kg", 1000.0), 0.1, 1e9, f"deposit {n!r} reserve_kg"),
                "taken_kg": number(d.get("taken_kg", 0.0), 0.0, 1e9, f"deposit {n!r} taken_kg")}
        out["deposits"].append(made)
    for i, s in enumerate(given.get("stockpiles") or []):
        if not isinstance(s, dict):
            raise ValueError(f"stockpile {i} is an object")
        n = name(s.get("name") or f"stockpile {i + 1}", f"stockpile {i}")
        if n in names:
            raise ValueError(f"two things in goods are called {n!r}")
        names.add(n)
        if not isinstance(s.get("at_m"), (list, tuple)) or len(s["at_m"]) != 2:
            raise ValueError(f"stockpile {n!r} at_m is [x, z] in metres")
        made = {"name": n,
                "at_m": [number(s["at_m"][0], -1000.0, 1000.0, f"stockpile {n!r} x"),
                         number(s["at_m"][1], -1000.0, 1000.0, f"stockpile {n!r} z")],
                "radius_m": number(s.get("radius_m", HEAP_RADIUS_M), 0.3, 20.0, f"stockpile {n!r} radius_m"),
                "holds": masses(s.get("holds") or {}, f"stockpile {n!r} holds")}
        if s.get("rack"):
            made["rack"] = True
        out["stockpiles"].append(made)
    for i, r in enumerate(given.get("recipes") or []):
        if not isinstance(r, dict):
            raise ValueError(f"recipe {i} is an object")
        n = name(r.get("name"), f"recipe {i}")
        if any(o["name"] == n for o in out["recipes"]):
            raise ValueError(f"two recipes are called {n!r}")
        ins = masses(r.get("in"), f"recipe {n!r} in", lo=0.0)
        outs = masses(r.get("out"), f"recipe {n!r} out", lo=0.0)
        if not ins or sum(ins.values()) <= 0.0:
            raise ValueError(f"recipe {n!r} takes something in: a map of substances to kilograms per batch")
        if not outs or sum(outs.values()) <= 0.0:
            raise ValueError(f"recipe {n!r} makes something: a map of substances to kilograms per batch")
        if sum(outs.values()) > sum(ins.values()) + 1e-9:
            raise ValueError(f"recipe {n!r} makes more mass than it takes in: {sum(outs.values()):g} kg out of "
                             f"{sum(ins.values()):g} kg in")
        out["recipes"].append({"name": n, "in": ins, "out": outs,
                               "work_j_per_kg": number(r.get("work_j_per_kg", 0.0), 0.0, 1e8, f"recipe {n!r} work_j_per_kg"),
                               "s_per_kg": number(r.get("s_per_kg", 1.0), 0.0, 3600.0, f"recipe {n!r} s_per_kg")})
    return out
