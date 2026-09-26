"""A new game's world: what is in the ground, where it is, and a proof that a
person can get from their first minute to everything the Workshop can build.

The owner, 2026-09-26: "it should generate a world with the appropriate mixture
of raw materials in the right locations such that a person could build
anything." Two halves, and the second is the point:

  * PLACE. From a seed, put deposits and heaps on the ground -- ore in the high
    ground, sand and clay by the water, timber where it fell -- each one dry,
    flat enough to work, clear of the others, and somewhere a machine can
    actually drive to.
  * PROVE. Then walk it. From what a new game starts with, can you reach every
    material and every good the Workshop spends? A map that strands something
    is thrown away and another is seeded. A generator that cannot say whether
    its world is playable is a random number generator.

WHY THIS EXISTS. A new game today is unwinnable, and it is worth writing down
exactly how. The Workshop's rover -- the only thing that digs -- costs 2.3 kg
of copper wire and 1.0 kg of copper, and copper wire is drawn from copper,
which is smelted from copper ore, which has to be DUG. You need the digger to
get the material to build the digger. A new player's goods rack holds nothing
at all, so the loop never starts. Their material rack is short too: 12.4 kg of
oak against the rover's 37.8, 6.2 kg of iron against 11.8, 0.6 kg of glass
against 4.0.

`progression/start.json` already forbids exactly this for the knowledge graph
-- "a player must not need a pickaxe to obtain the only material capable of
making their first pickaxe" -- and the world has never been held to the same
rule. This module holds it to it.

HOW THE CIRCLE IS BROKEN. Not with new physics: by what the start HOLDS. A new
game begins with one digger and one processor already standing, the way
Factorio hands you a burner drill and a furnace. Everything after that is
earned. The proof checks both directions -- that the start is ENOUGH (nothing
is stranded) and that it is not MORE than enough (take any one thing out of it
and something strands). A starting gift that quietly includes the whole game is
not a bootstrap.

WHAT IS HONESTLY NOT HERE.

  * Only a machine can gather. `Goods.dug` is reached from one place in the
    whole program (machine_tools, the scoop), so a person on foot cannot pick
    up so much as a handful of sand. Every route in the proof runs through a
    machine, because every route in the game does.
  * Nothing regrows. Timber is a heap that was there when you arrived, ore is
    a reserve that runs out. A world can be exhausted and this proof will still
    call it playable, because it proves you can REACH a material, not that you
    can have it forever.
  * Rubber and ice have no source anywhere in the game's data, so no map can
    supply them. That is not the map's fault and it does not make the map
    regenerate: the proof reports them as missing from the world rather than
    stranded in it, which is the difference between a bad roll and a to-do.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Iterable

SEED_SCHEMA = "banjo.world-seed.v1"

# ---------------------------------------------------------------------------
# What a kilogram of work costs
# ---------------------------------------------------------------------------
# Every recipe's work is the real specific energy of making that substance,
# times this. A battery in this game holds a couple of megajoules and a day
# passes in minutes, so real industry -- 20 MJ to win a kilogram of copper --
# would empty a rover before it filled its hopper. Scaling them all by one
# number keeps what matters, which is what each thing costs RELATIVE to the
# others: aluminium stays eight times dearer than copper, concrete stays
# nearly free.
#
# The scale is not chosen, it is read off. The two recipes that already
# existed before this file -- the mine room's "smelt copper" at 2,000 J/kg and
# "draw wire" at 500 -- are 20 MJ/kg and 5 MJ/kg at exactly 1e-4, which are the
# real figures for pyrometallurgical copper and for drawing and annealing it.
# Whoever wrote those two was working to this scale without saying so.
WORK_SCALE = 1.0e-4


@dataclass(frozen=True)
class Seam:
    """Something in the ground, and the kind of place it is found in.

    `grade` is the share of a scoop's mass that comes up as the substance, the
    way machine_goods spends it; `reserve_kg` is how much is there before the
    patch is worked out.
    """
    substance: str
    ground: str                      # "high", "by the water", or "open"
    grade: float
    reserve_kg: tuple[float, float]  # least and most, rolled per vein
    veins: tuple[int, int]           # how many of them, least and most
    radius_m: tuple[float, float]
    note: str = ""


@dataclass(frozen=True)
class Heap:
    """Something lying on the ground when you arrive, in a stockpile a machine
    can take from. Not dug: found."""
    substance: str
    ground: str
    kg: tuple[float, float]
    note: str = ""


@dataclass(frozen=True)
class Step:
    """One recipe: what it takes, what comes out, and what it costs.

    `out` is by mass per kilogram in, as machine_goods reads it -- what is
    missing from the out side is lost as waste, which is where the rock in an
    ore and the water in a clay go.
    """
    name: str
    takes: dict[str, float]
    makes: dict[str, float]
    real_mj_per_kg: float
    s_per_kg: float
    note: str = ""

    def as_recipe(self) -> dict[str, Any]:
        """The room's own spelling of it (machine_goods, "recipes")."""
        return {"name": self.name, "in": dict(self.takes), "out": dict(self.makes),
                "work_j_per_kg": round(self.real_mj_per_kg * 1.0e6 * WORK_SCALE, 1),
                "s_per_kg": self.s_per_kg}


# ---------------------------------------------------------------------------
# What this world is made of
# ---------------------------------------------------------------------------
# Grades and yields are the real ones, because there is no reason for them not
# to be and a made-up number teaches a player something false.

# Radii are in metres and they are SMALL, because the valley is small: 39 by
# 31 m of ground, of which about a fifth is drivable from where a person
# arrives. A 4 m vein is a quarter of the reachable width. Where even these do
# not fit, `place` shrinks them rather than dropping the seam.
GROUND_HOLDS: tuple[Seam, ...] = (
    Seam("copper ore", "high", 0.30, (300.0, 900.0), (1, 2), (1.2, 1.8),
         "a vein in the high ground, at the 0.3 the mine room already digs"),
    Seam("iron ore", "high", 0.55, (600.0, 1600.0), (1, 2), (1.2, 1.8),
         "hematite runs about 55-60% iron where it is worth digging"),
    Seam("bauxite", "high", 0.35, (300.0, 800.0), (1, 1), (1.0, 1.5),
         "lateritic, so it weathers out on flat high ground rather than in a vein"),
    Seam("limestone", "high", 0.60, (600.0, 1600.0), (1, 2), (1.2, 1.8),
         "an exposed bed; what is not limestone is the overburden with it"),
    Seam("sand", "by the water", 0.80, (800.0, 2000.0), (2, 3), (1.2, 1.8),
         "a river bar: nearly all sand, which is why glass is made by rivers"),
    Seam("clay", "by the water", 0.60, (400.0, 1200.0), (1, 2), (1.0, 1.5),
         "floodplain clay, wet and mixed with the silt over it"),
)

LIES_ABOUT: tuple[Heap, ...] = (
    Heap("oak", "open", (120.0, 260.0),
         "fallen timber. NOTHING REGROWS: this is the only oak the world will "
         "ever have, and when it is gone it is gone"),
)

CHAIN: tuple[Step, ...] = (
    Step("smelt copper", {"copper ore": 1.0}, {"copper": 0.30}, 20.0, 2.0,
         "concentrate to cathode; the mine room's own recipe, unchanged"),
    Step("draw wire", {"copper": 1.0}, {"copper wire": 0.98}, 5.0, 1.0,
         "drawing and annealing; the mine room's own recipe, unchanged"),
    Step("smelt iron", {"iron ore": 1.0}, {"iron": 0.62}, 20.0, 2.5,
         "blast furnace to basic oxygen steel, about 20 MJ/kg all told"),
    Step("smelt aluminium", {"bauxite": 1.0}, {"aluminum": 0.25}, 170.0, 4.0,
         "four tonnes of bauxite to two of alumina to one of metal, and "
         "Hall-Heroult is the dearest thing in the game by a long way"),
    Step("melt glass", {"sand": 1.0}, {"glass": 0.85}, 8.0, 3.0,
         "a float furnace; the batch loses its carbon dioxide"),
    Step("fire ceramic", {"clay": 1.0}, {"alumina ceramic": 0.70}, 10.0, 4.0,
         "water and loss on ignition take the rest"),
    Step("burn lime", {"limestone": 1.0}, {"cement": 0.56}, 4.0, 3.0,
         "calcination: calcium carbonate loses 44% of its mass as gas"),
    Step("mix concrete", {"cement": 0.15, "sand": 0.85}, {"concrete": 1.0}, 0.5, 0.5,
         "one of cement to six of aggregate; the water is not tracked"),
)

#: What the Workshop spends and therefore what a world has to be able to
#: supply: the eight materials its rack is kept in, and the goods its machines
#: are made of beyond their matter. Read from the library so that adding a
#: material to the game adds it to this proof.
def wants() -> dict[str, list[str]]:
    from workshop_library import DEFAULT_RACK, GOODS_PER
    return {"materials": sorted(DEFAULT_RACK),
            "goods": sorted({substance for substance, *_ in GOODS_PER.values()})}


#: Materials nothing in the game's data can make, at any price, from any map.
#: Kept as a named list rather than discovered, so that the day one of them
#: gets a source the list is what fails.
NO_SOURCE_ANYWHERE = {
    "rubber": "no tree, no oil, and no recipe: rubber is on the rack at the "
              "start and can never be replaced",
    "ice": "water freezes in the world (docs, melting) but nothing puts ice on "
           "a rack, so it cannot be built with",
}


# ---------------------------------------------------------------------------
# What a new game starts with
# ---------------------------------------------------------------------------
# One digger and one processor, already standing. Their cost is not written
# here -- it is read from the designs themselves, so that making the rover
# heavier makes the bootstrap heavier and the minimality check notices.

#: The kinds the start puts on the ground. A digger to get raw material out,
#: and a processor to turn it into something, which is the smallest pair that
#: closes the loop: with only the digger you have ore and no way to smelt it,
#: and with only the processor you have nothing to smelt.
STARTS_STANDING = ("rover", "smelter")

#: What a machine standing in the world lets you do. A rover digs and hauls; a
#: still machine on a block works a recipe.
DOES = {"rover": ("dig", "haul"), "drone": ("haul",), "smelter": ("process",),
        "mill": ("process",)}


def costs(kind: str) -> dict[str, dict[str, float]]:
    """What one of these takes to build: its matter, by material, and its
    goods, by substance.

    Straight off the design where there is one, so these are the real numbers
    the install gate charges and not a second copy of them that can drift.
    """
    import workshop_library as library
    from mcp import engine_materials, workshop as w

    if kind in ("smelter", "mill"):
        # A still machine is not an assembly: it is the mine room's concrete
        # block with a battery, a panel and a control on it
        # (tools/build_mine_room.py, BLOCK_M and STILL). Its cost is that
        # block's matter plus what GOODS_PER charges for those parts.
        volume = 0.6 * 0.8 * 0.6
        concrete = volume * engine_materials.density("concrete")
        goods = {"copper": round(1.0e-5 * 2.0e6, 4),        # a 2 MJ store
                 "copper wire": round(0.5 * 0.3 + 0.1, 4)}  # a 0.3 m2 panel, and its control
        return {"materials": {"concrete": round(concrete, 3)}, "goods": goods}

    design = w.assemble(kind, design_id=f"start-{kind}")
    materials: dict[str, float] = {}
    for part in design.parts:
        material = engine_materials.canonical(part.material)
        try:
            kg = part.volume_m3() * engine_materials.density(material)
        except KeyError:
            kg = part.mass_kg()
        materials[material] = round(materials.get(material, 0.0) + kg, 3)
    return {"materials": materials, "goods": library.goods_needed(design)}


def start() -> dict[str, Any]:
    """A new game: what stands in the world, and what that is worth."""
    standing = {kind: costs(kind) for kind in STARTS_STANDING}
    return {"standing": list(STARTS_STANDING), "costs": standing,
             "can": sorted({verb for kind in STARTS_STANDING for verb in DOES.get(kind, ())})}


# ---------------------------------------------------------------------------
# The proof: can you make it
# ---------------------------------------------------------------------------

@dataclass
class Route:
    """How a substance is got: the steps in order, ending in it."""
    substance: str
    how: list[str]

    def __str__(self) -> str:
        return f"{self.substance} <- " + " <- ".join(reversed(self.how)) if self.how else \
               f"{self.substance} (had it at the start)"


def can_make(goods_block: dict[str, Any], *, can: Iterable[str],
             held: Iterable[str] = ()) -> dict[str, Route]:
    """Everything obtainable in this world, and the route to each.

    A fixed point over three ways of getting something: it was in the ground
    and you can dig, it was lying about and you can haul, or a recipe makes it
    from things you can already get and you can process. Every one of those
    needs a machine, which is why `can` is a set of verbs and not a flag: a
    world full of copper with nothing that digs yields nothing.
    """
    verbs = set(can)
    reached: dict[str, Route] = {s: Route(s, []) for s in held}
    if "dig" in verbs:
        for deposit in goods_block.get("deposits") or []:
            substance = str(deposit.get("substance") or "")
            reached.setdefault(substance, Route(substance, [f"dug from {deposit.get('name')}"]))
    if "haul" in verbs:
        for pile in goods_block.get("stockpiles") or []:
            for substance, kg in (pile.get("holds") or {}).items():
                if float(kg) > 0.0:
                    reached.setdefault(substance, Route(substance, [f"taken from {pile.get('name')}"]))
    if "process" in verbs:
        recipes = list(goods_block.get("recipes") or [])
        moved = True
        while moved:
            moved = False
            for recipe in recipes:
                takes = recipe.get("in") or {}
                if not takes or any(s not in reached for s in takes):
                    continue
                deepest = max((reached[s].how for s in takes), key=len, default=[])
                for substance, out in (recipe.get("out") or {}).items():
                    if float(out) > 0.0 and substance not in reached:
                        reached[substance] = Route(substance, list(deepest) + [str(recipe.get("name"))])
                        moved = True
    return reached


def prove_you_can_make_it(goods_block: dict[str, Any], *, can: Iterable[str],
                          held: Iterable[str] = ()) -> dict[str, Any]:
    """Every material and good the Workshop spends, and whether this world can
    supply it.

    Three answers, and keeping them apart is the whole value of this: REACHED,
    STRANDED (the game could supply it and this map does not -- a bad roll,
    seed another), and NOT IN THE WORLD (nothing anywhere can supply it -- a
    to-do, and no amount of re-rolling will fix it).
    """
    asked = wants()
    reached = can_make(goods_block, can=can, held=held)
    out: dict[str, Any] = {"reached": {}, "stranded": {}, "not in the world": {}}
    for substance in asked["materials"] + asked["goods"]:
        if substance in reached:
            out["reached"][substance] = str(reached[substance])
        elif substance in NO_SOURCE_ANYWHERE:
            out["not in the world"][substance] = NO_SOURCE_ANYWHERE[substance]
        else:
            out["stranded"][substance] = _why_stranded(substance, goods_block, reached, can)
    out["ok"] = not out["stranded"]
    return out


def _why_stranded(substance: str, goods_block: dict[str, Any],
                  reached: dict[str, Route], can: Iterable[str],
                  seen: frozenset[str] = frozenset()) -> str:
    """The reason, chased down to the thing somebody can actually change.

    "There is no ceramic" is not a reason. "Firing clay would make it, and
    this map could not fit a clay seam anywhere a machine can work" is one:
    it names the recipe, the missing input, and which of the two halves of the
    generator went wrong. So a recipe whose input is missing asks the same
    question of the input, down to the ground.
    """
    verbs = set(can)
    makes = [r for r in (goods_block.get("recipes") or []) if substance in (r.get("out") or {})]
    in_ground = [d for d in (goods_block.get("deposits") or [])
                 if d.get("substance") == substance]
    lying = [p for p in (goods_block.get("stockpiles") or [])
             if float((p.get("holds") or {}).get(substance, 0.0)) > 0.0]
    if in_ground and "dig" not in verbs:
        return f"it is in the ground here ({in_ground[0].get('name')}) and nothing can dig"
    if lying and "haul" not in verbs:
        return f"it is lying there in the {lying[0].get('name')} and nothing can haul"
    if makes and "process" not in verbs:
        return f"{makes[0].get('name')} would make it and nothing can process"
    for recipe in makes:
        missing = sorted(s for s in (recipe.get("in") or {}) if s not in reached)
        if not missing:
            continue
        said = f"{recipe.get('name')} would make it but there is no {', no '.join(missing)}"
        if missing[0] in seen:          # a chain that eats its own tail
            return said
        deeper = _why_stranded(missing[0], goods_block, reached, can, seen | {substance})
        return f"{said} -- and {deeper}"
    if not makes and not in_ground and not lying:
        # The game knows of it but this map has none: the placement ran out of
        # workable ground, which is a bad roll and not a missing feature.
        elsewhere = ([s for s in GROUND_HOLDS if s.substance == substance] +
                     [h for h in LIES_ABOUT if h.substance == substance])
        if elsewhere:
            return "this map could not fit it anywhere a machine can work"
        return "nothing in this map holds it and no recipe makes it"
    return "no route to it"


def prove_it_is_only_just_enough(goods_block: dict[str, Any], *,
                                 can: Iterable[str]) -> dict[str, Any]:
    """Take one verb away from the start and check that something strands.

    A bootstrap that still works with a piece removed was not a bootstrap, it
    was a gift. This is the check that stops the start quietly growing until a
    new game is handed the finished game.
    """
    out: dict[str, Any] = {"needed": {}, "spare": {}}
    for verb in sorted(set(can)):
        without = sorted(set(can) - {verb})
        proof = prove_you_can_make_it(goods_block, can=without)
        if proof["stranded"]:
            out["needed"][verb] = f"without it: no {', no '.join(sorted(proof['stranded'])[:4])}"
        else:
            out["spare"][verb] = "everything is still reachable without it"
    out["ok"] = not out["spare"]
    return out


# ---------------------------------------------------------------------------
# The proof: can you get there
# ---------------------------------------------------------------------------
# A wheeled machine climbs a slope or it does not. This is the rise between one
# heightfield sample and the next that stops a rover, as a fraction: 0.35 is
# about 19 degrees.
#
# NOT MEASURED. It is a declared limit, chosen because it is under the 20% a
# table topples on (tools/build_explore_world) and over the grade of every road
# a person would build. What a rover can really climb is a question for the
# engine and nobody has put it. Until somebody does, a world proved drivable
# here is proved against this number and not against the rover.
CLIMB = 0.35

#: How flat the ground has to be over a deposit before a machine can work it:
#: the rise and fall across the whole patch, in metres.
WORKABLE_SPREAD_M = 0.9


def drivable(ground: dict[str, Any], from_xz: tuple[float, float]) -> set[tuple[int, int]]:
    """Which of the ground's samples a wheeled machine can get to from here.

    A flood fill over the heightfield: step to a neighbour if it is dry and the
    rise between them is under CLIMB. This is the half of reachability that a
    substance graph cannot see -- a copper vein on the far side of the river is
    in the world, in the ground, and of no use to anybody.
    """
    nx, nz, cell = ground["nx"], ground["nz"], ground["cell"]
    wet = ground.get("wet") or set()
    height = ground["h"]

    def at(i: int, j: int) -> float:
        return height[j * nx + i]

    i0 = min(nx - 1, max(0, int(round((from_xz[0] - ground["x0"]) / cell))))
    j0 = min(nz - 1, max(0, int(round((from_xz[1] - ground["z0"]) / cell))))
    if (i0, j0) in wet:
        return set()
    seen = {(i0, j0)}
    edge = [(i0, j0)]
    while edge:
        i, j = edge.pop()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if not (0 <= a < nx and 0 <= b < nz) or (a, b) in seen or (a, b) in wet:
                continue
            if abs(at(a, b) - at(i, j)) / cell > CLIMB:
                continue
            seen.add((a, b))
            edge.append((a, b))
    return seen


def _cell_of(ground: dict[str, Any], x: float, z: float) -> tuple[int, int]:
    return (int(round((x - ground["x0"]) / ground["cell"])),
            int(round((z - ground["z0"]) / ground["cell"])))


def prove_you_can_get_there(ground: dict[str, Any], goods_block: dict[str, Any],
                            from_xz: tuple[float, float]) -> dict[str, Any]:
    """Every deposit and heap, and whether a machine can drive to it."""
    there = drivable(ground, from_xz)
    out: dict[str, Any] = {"reachable": [], "cut off": {}}
    places = [(d.get("name"), d.get("at_m")) for d in (goods_block.get("deposits") or [])]
    places += [(p.get("name"), p.get("at_m")) for p in (goods_block.get("stockpiles") or [])]
    for name, at in places:
        if not at:
            continue
        if _cell_of(ground, float(at[0]), float(at[1])) in there:
            out["reachable"].append(name)
        else:
            out["cut off"][name] = f"no way to drive from {from_xz[0]:.0f}, {from_xz[1]:.0f} to it"
    out["ok"] = not out["cut off"]
    return out


# ---------------------------------------------------------------------------
# The ground, as a heightfield
# ---------------------------------------------------------------------------
# The same dict `tools/build_explore_world.read_ground` makes from a live
# world: nx, nz, cell, x0, z0, a flat list of heights and the set of samples
# under water. These three are its three, kept here so that generating and
# proving a world needs nothing out of tools/ -- that builder is a script, this
# is what a server calls when somebody starts a new game.


def height_at(ground: dict[str, Any], x: float, z: float) -> float:
    i, j = _cell_of(ground, x, z)
    i = min(ground["nx"] - 1, max(0, i))
    j = min(ground["nz"] - 1, max(0, j))
    return ground["h"][j * ground["nx"] + i]


def flatness(ground: dict[str, Any], x: float, z: float, radius_m: float) -> float:
    """How much the ground rises and falls over a patch: high minus low."""
    step = ground["cell"]
    n = max(1, int(radius_m / step))
    seen = [height_at(ground, x + a * step, z + b * step)
            for a in range(-n, n + 1) for b in range(-n, n + 1)]
    return max(seen) - min(seen)


def wet_near(ground: dict[str, Any], x: float, z: float, radius_m: float) -> bool:
    wet = ground.get("wet") or set()
    if not wet:
        return False
    i0, j0 = _cell_of(ground, x - radius_m, z - radius_m)
    i1, j1 = _cell_of(ground, x + radius_m, z + radius_m)
    return any((i, j) in wet for j in range(j0, j1 + 1) for i in range(i0, i1 + 1))


# ---------------------------------------------------------------------------
# Placing it
# ---------------------------------------------------------------------------
#: Of the places a machine can work, the share nearest the water that counts
#: as a bank, and the share of the rest, by height, that counts as high
#: ground.
#:
#: SHARES, NOT DISTANCES, and that is the whole of it. The first version asked
#: for dry ground within four metres of the river, which in the valley is 482
#: of its 575 workable patches: nearly all of it is riverbank, so there was
#: nowhere left to put an ore and the generator gave up twelve times running.
#: A share sorts any valley -- a gorge and a floodplain both have a nearest
#: third -- and a map with no water at all simply has no banks, which the
#: fallback in `pick` handles.
BANK_SHARE = 0.33
HIGH_SHARE = 0.33
#: A hand's width of daylight between one patch and the next, as the Explore
#: builder keeps between things it sets down.
CLEAR_M = 0.5
#: How small a seam may be squeezed before it is not a seam. `place` shrinks a
#: vein that will not fit rather than leaving the substance out of the world,
#: because a missing substance strands the whole map and a smaller vein only
#: makes it a longer drive.
LEAST_RADIUS_M = 0.6


#: The patch size every candidate is first sifted at. A place that cannot take
#: this cannot take any seam, and one that can is checked again at its own
#: radius when it is picked -- one scan of the ground instead of one per vein.
SIFT_M = 2.0


def _to_water(ground: dict[str, Any]) -> dict[tuple[int, int], int]:
    """How many samples every bit of ground is from the nearest water, as a
    flood out from the wet cells. One pass, then every patch can ask."""
    wet = ground.get("wet") or set()
    nx, nz = ground["nx"], ground["nz"]
    far = {cell: 0 for cell in wet}
    edge = list(wet)
    while edge:
        nxt = []
        for i, j in edge:
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = i + di, j + dj
                if 0 <= a < nx and 0 <= b < nz and (a, b) not in far:
                    far[(a, b)] = far[(i, j)] + 1
                    nxt.append((a, b))
        edge = nxt
    return far


def _patches(ground: dict[str, Any], there: set[tuple[int, int]],
             stride: int = 2) -> list[tuple[float, float, str, float]]:
    """Every place on this ground a machine could work a patch: where it is,
    what kind of ground it is, and how high.

    Dry over the patch, flat enough to work, and drivable to. The kind is what
    decides which substance goes there -- ore in the high ground, sand and clay
    on the banks -- and it is read off the ground rather than declared, so a
    different valley sorts itself out.
    """
    cell = ground["cell"]
    far = _to_water(ground)
    found = []
    for j in range(0, ground["nz"], stride):
        for i in range(0, ground["nx"], stride):
            if (i, j) not in there:
                continue
            x, z = ground["x0"] + i * cell, ground["z0"] + j * cell
            if wet_near(ground, x, z, SIFT_M + CLEAR_M):
                continue
            if flatness(ground, x, z, SIFT_M) > WORKABLE_SPREAD_M:
                continue
            found.append((x, z, far.get((i, j), 1 << 20), height_at(ground, x, z)))
    if not found:
        return []
    nearness = sorted(d for _, _, d, _ in found)
    bank_to = nearness[int(BANK_SHARE * (len(nearness) - 1))]
    inland = sorted(h for _, _, d, h in found if d > bank_to)
    high_from = inland[int((1.0 - HIGH_SHARE) * (len(inland) - 1))] if inland else math.inf
    return [(x, z, "by the water" if d <= bank_to else ("high" if h >= high_from else "open"), h)
            for x, z, d, h in found]


def place(ground: dict[str, Any], seed: int, *,
          start_xz: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
    """Seed a map: what is in this ground, where, and how much of it.

    Deterministic in `seed`: the same seed and the same ground give the same
    world, byte for byte, which is what makes a bad roll reportable and a good
    one shareable.
    """
    roll = random.Random(seed)
    there = drivable(ground, start_xz)
    patches = _patches(ground, there)
    taken: list[tuple[float, float, float]] = [(start_xz[0], start_xz[1], 3.0)]
    deposits: list[dict[str, Any]] = []
    stockpiles: list[dict[str, Any]] = []

    def fits(x: float, z: float, radius: float) -> bool:
        if any(math.dist((x, z), (tx, tz)) <= radius + tr + CLEAR_M for tx, tz, tr in taken):
            return False
        if radius <= SIFT_M:      # already sifted at this size or larger
            return True
        return (not wet_near(ground, x, z, radius + CLEAR_M)
                and flatness(ground, x, z, radius) <= WORKABLE_SPREAD_M)

    def pick(kind: str, radius: float,
             near: tuple[float, float] | None = None) -> tuple[float, float, float] | None:
        """Somewhere of this kind that will take a patch this big, or the best
        compromise: the right kind of ground first, then any ground, and a
        smaller patch before no patch at all.

        With `near`, the closest such place to a point rather than a rolled
        one -- how the start's own yard is laid out, because a rack the player
        cannot see is a rack they will never find.
        """
        for want in (kind, "open", None):
            here = [(x, z) for x, z, k, _ in patches if want is None or k == want]
            if not here:
                continue
            size = radius
            while size >= LEAST_RADIUS_M:
                able = sorted((x, z) for x, z in here if fits(x, z, size))
                if able:
                    x, z = min(able, key=lambda p: math.dist(p, near)) if near else roll.choice(able)
                    return x, z, round(size, 2)
                size *= 0.75
        return None

    # The start's yard goes down before anything else, by where the player
    # arrives: the heaps the first smelter works between, and the Workshop's
    # own rack, which is the one stockpile whose contents can be built with.
    # It is FIRST for the same reason the timber is early -- it has exactly one
    # acceptable place, and laid down last it lost every time. Placed after the
    # seams it fell back to the start's own feet on all three, because nine
    # veins and their clearances had covered every workable patch within eight
    # metres.
    for name, extra in (("workshop rack", {"rack": True}),
                        ("smelter intake", {}), ("smelter output", {})):
        got = pick(None, 1.0, near=start_xz)
        x, z, radius = got if got else (start_xz[0], start_xz[1], 1.0)
        taken.append((x, z, radius))
        stockpiles.append({"name": name, "at_m": [round(x, 2), round(z, 2)],
                           "radius_m": radius, **extra})

    # ORDER IS THE DIFFERENCE BETWEEN A PLAYABLE MAP AND A BAD ROLL. Laid down
    # seam by seam, with the timber last, 25 of 60 seeds of the valley had no
    # room left for the one oak pile in the world and stranded every wooden
    # thing in the game; four more could not fit their clay. So everything
    # takes its FIRST place before anything takes a second: the heaps first,
    # because a heap is the only source of what is in it, then one vein of
    # each seam, then the spares. A second copper vein is a convenience, a
    # first clay seam is the whole of ceramics.
    wanted = [(heap, 0) for heap in LIES_ABOUT]
    wanted += [(seam, 0) for seam in GROUND_HOLDS]
    wanted += [(seam, n) for seam in GROUND_HOLDS for n in range(1, roll.randint(*seam.veins))]

    for thing, n in wanted:
        if isinstance(thing, Heap):
            got = pick(thing.ground, 1.0)
            if got is None:
                continue
            x, z, radius = got
            taken.append((x, z, radius))
            stockpiles.append({"name": f"{thing.substance} pile",
                               "at_m": [round(x, 2), round(z, 2)], "radius_m": radius,
                               "holds": {thing.substance: round(roll.uniform(*thing.kg), 1)}})
            continue
        got = pick(thing.ground, round(roll.uniform(*thing.radius_m), 2))
        if got is None:
            continue
        x, z, radius = got
        taken.append((x, z, radius))
        name = thing.substance if n == 0 else f"{thing.substance} {n + 1}"
        deposits.append({"name": f"{name} seam", "substance": thing.substance,
                         "at_m": [round(x, 2), round(z, 2)], "radius_m": radius,
                         "grade": thing.grade,
                         "reserve_kg": round(roll.uniform(*thing.reserve_kg), 1)})

    return {"deposits": deposits, "stockpiles": stockpiles,
            "recipes": [step.as_recipe() for step in CHAIN]}


def new_world(ground: dict[str, Any], seed: int = 1, *, tries: int = 12,
              start_xz: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
    """A new game: seed a map, prove it, and seed another if it strands
    anything.

    Returns the goods block and the proof that went with it. A world nobody
    proved is a world nobody knows is playable, so the proof travels with it
    and is written into the room.
    """
    began = start()
    last: dict[str, Any] = {}
    for attempt in range(tries):
        goods = place(ground, seed + attempt, start_xz=start_xz)
        make = prove_you_can_make_it(goods, can=began["can"])
        get = prove_you_can_get_there(ground, goods, start_xz)
        last = {"schema": SEED_SCHEMA, "seed": seed + attempt, "tries": attempt + 1,
                "start": began, "can make it": make, "can get there": get,
                "ok": bool(make["ok"] and get["ok"])}
        if last["ok"]:
            return {"goods": goods, "proof": last}
    raise ValueError("no playable world in {} tries from seed {}: {}".format(
        tries, seed, last.get("can make it", {}).get("stranded") or
        last.get("can get there", {}).get("cut off")))
