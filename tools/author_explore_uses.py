#!/usr/bin/env python3
"""Have the Workshop's own model decide how each of the Explore valley's
products is used, once, and keep what it decides.

    python tools/author_explore_uses.py              # every product in the valley
    python tools/author_explore_uses.py chair stool  # just these

The owner, 2026-09-21: every object should have the model determine "the
primary use of the object for the main use key to control and where the user
would be 'holding' it or where it would hit or be hit or stack or be stacked".
The valley's things had none of it: a hand-written table gave every piece of
furniture "Shove it along", and every grip was a part's middle.

So each product goes through the Workshop chat (playground/workshop_chat.py),
the same model and the same two tools a person's Workshop session uses:
`program_use` for its one Use, and `define_interaction_points` for its grip,
the part that does its work, and the surfaces and cavities things go on or in.
What it writes is saved in tools/explore_uses.json -- with the model, the date
and its own words -- and tools/build_explore_world.py builds the valley from
that file, so a rebuild asks no model and comes out the same every time.

Needs OPENAI_API_KEY where the playground finds it (the checkout's .env). A
handful of model calls per product.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

import server               # noqa: E402  where the key and the model are found
import workshop_api_core    # noqa: E402
import workshop_chat        # noqa: E402
import workshop_library     # noqa: E402
from mcp import workshop_components, workshop_construction  # noqa: E402
from mcp.workshop import assembly     # noqa: E402

OUT = ROOT / "tools" / "explore_uses.json"
# The valley's Workshop products (tools/build_explore_world.py compose()): the
# five built of cells, and the cart, which stands as exact bodies on pins.
KINDS = ("table", "bench", "chair", "stool", "shelf-unit", "cart")

PROMPT = """This {kind} is about to be placed, as it is, in the Explore valley: a world a person walks around in first person. There E takes ANY thing up -- one hand holds it at its grip point -- and E again puts it down where they look, so carrying and setting down are never its use. The left mouse runs its primary use: what it is FOR beyond being carried. Other things can be set on or in it. Decide from what it is for. Change nothing about its geometry.

1. Call program_use with its one primary use: one core step -- push_forward (it is shoved or slid along the ground without being lifted: a table slid across, a chair pushed in), strike (it is held and swung at something: a club, a hammer), or inspect when a person does nothing more with it than carry it and set things on it. Not place: E already does that for everything. Its label is what the left mouse DOES, in a few words a person reads before pressing it: an inspect is "Look at it", never something this world cannot do yet (nobody can sit or lie down here).
2. Call define_interaction_points with: ONE grip, where a person's hand holds it to carry it; ONE use point, on the part that does its work; and a surface point for every real surface something can be set on (a container point for every real cavity), each with its usable size.

The hand is one hand: strong (800 N) but with a wrist that holds only 60 N m, so a heavy thing gripped away from its centre of mass hangs tipped. For anything heavier than a few kilograms put the grip on a part directly above its centre of mass, so it hangs level. Every grip and use point is ON the thing, on the surface of one of its parts -- never in the air beside or above it. Inspect the design first for where its parts are. Positions are metres in the design frame."""

# A point further than this outside every part is not on the thing.
ON_THE_THING_M = 0.02


def off_the_thing(design, points: list[dict]) -> list[str]:
    """Points that are not where they say: a grip or use point on no part of the
    design -- the model once put a table's grip 0.14 m above its top, which a
    hand would hold by nothing -- and a surface on no part's top face: it once
    put a cart's deck on the ground under the cart. Each part is measured as it
    is turned (the box round its corners), so a cart's handle, a bar lying
    across, is where it is drawn."""
    boxes = [workshop_construction._bounds(part) for part in design.parts]
    bad = []
    for point in points:
        at = point["position_m"]
        if point.get("kind") in ("grip", "use"):
            on = any(all(lo[a] - ON_THE_THING_M <= at[a] <= hi[a] + ON_THE_THING_M for a in range(3))
                     for lo, hi in boxes)
        elif point.get("kind") == "surface":
            # On the face things rest on, or in the board under it by up to half
            # its thickness (3 cm at most): the model puts a table's surface at
            # the middle of its top, and the engine finds the face itself.
            on = any(hi[1] - min((hi[1] - lo[1]) / 2, 0.03) - 1e-6 <= at[1] <= hi[1] + ON_THE_THING_M and
                     all(lo[a] - ON_THE_THING_M <= at[a] <= hi[a] + ON_THE_THING_M for a in (0, 2))
                     for lo, hi in boxes)
        else:
            continue
        if not on:
            bad.append(f"{point['kind']} {point['id']} at {[round(v, 3) for v in at]}")
    return bad


def author(app, kind: str, tries: int = 3) -> dict:
    """The model's use and points for one product. A point it puts off the
    thing is said back to it, as a person would, and it is asked again; after
    `tries` nothing is saved."""
    design, overrides = workshop_components.design_from_spec(
        {"kind": kind, "design_id": kind, "parameters": {}})
    book = workshop_library.pricebook(app)
    ask = PROMPT.format(kind=kind)
    for attempt in range(1, tries + 1):
        candidate = workshop_api_core._candidate(app, design, assembly(kind), overrides)
        said = workshop_chat.propose(app, message=ask, selected_part=None, candidate=candidate,
                                     materials=[m["material"] for m in book["materials"]], library=[])
        parameters = candidate.get("parameters") or {}
        missing = [k for k in ("primary_use", "interaction_points") if k not in parameters]
        if missing:
            raise SystemExit(f"{kind}: the model did not write {', '.join(missing)}; it said: {said['reply']!r}")
        bad = off_the_thing(design, parameters["interaction_points"])
        if not bad:
            return {"primary_use": parameters["primary_use"],
                    "interaction_points": parameters["interaction_points"],
                    "said": said["reply"], "tries": attempt,
                    "tools": [f"{t['tool']}: {t['summary']}" for t in said.get("tool_trace") or []]}
        print(f"  {kind:10s} try {attempt}: not on the {kind}: {'; '.join(bad)}", flush=True)
        ask = (PROMPT.format(kind=kind) + f"\n\nA try before this one put these where no part of the {kind} "
               f"is: {'; '.join(bad)}. Inspect where its parts are, and put each grip and use point on "
               f"a part, and each surface on the top face of what things rest on.")
    raise SystemExit(f"{kind}: after {tries} tries the model still put points off the {kind}. "
                     f"Nothing was saved for it.")


def main(argv: list[str]) -> int:
    kinds = argv or list(KINDS)
    unknown = sorted(set(kinds) - set(KINDS))
    if unknown:
        raise SystemExit(f"not a product in the valley: {', '.join(unknown)}")
    key, model = server.local_configuration()
    if not key:
        raise SystemExit("OPENAI_API_KEY is not configured where the playground looks for it")
    kept = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    products = dict(kept.get("products") or {})
    with tempfile.TemporaryDirectory() as tmp:
        # A library of its own, so the run touches nobody's saved designs.
        app = types.SimpleNamespace(api_key=key, model=model,
                                    workshop_db=str(Path(tmp) / "banjo.db"))
        for kind in kinds:
            print(f"  {kind:10s} asking {model} ...", flush=True)
            products[kind] = author(app, kind)
            use = products[kind]["primary_use"]
            points = products[kind]["interaction_points"]
            print(f"  {kind:10s} use {use['label']!r} ({', '.join(s['do'] for s in use['steps'])}); "
                  + ", ".join(f"{p['kind']} {p['id']}" for p in points), flush=True)
    OUT.write_text(json.dumps({
        "about": "Each product's primary use and interaction points, as the Workshop's own "
                 "model wrote them (tools/author_explore_uses.py). Read by "
                 "tools/build_explore_world.py; edit by running that script again.",
        "model": model, "written": _dt.date.today().isoformat(), "prompt": PROMPT,
        "products": products}, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
