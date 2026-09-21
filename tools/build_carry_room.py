#!/usr/bin/env python3
"""Compose the carry room: things of several parts, to take up whole.

    BANJO_LIBRARY=.../banjo.dll python tools/build_carry_room.py

Writes playground/rooms/tests-carry.json, which world_room serves as the
`tests-carry` scene; open it in the Explorer at /explore?scene=tests-carry.

The owner, 2026-09-21: "when a user picks up something it can be for the
entire product so that it doesn't break, but needs to still allow movement if
part of the product, like swinging a mace". So this room holds the two kinds of
thing that rule is about, each built by the chat's own recipe (banjo_mcp.
RECIPES) on the world's bare ground -- its east terrace, about 0.6 m up and
level -- exactly as the chat would build it:

  * a mace whose iron head hangs on a chain from its handle: taken up by either
    part, all of it comes, and the head goes on swinging;
  * a table with a chair drawn up to it, each of boards fixed to each other:
    taken up by the seat, the whole chair comes, rigid.

Re-run it to rebuild the room from the recipes; nothing is hand-edited in the
JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "playground")]

import room_world   # noqa: E402
import world_room   # noqa: E402

OUT = ROOT / "playground" / "rooms" / "tests-carry.json"
# Where each is built on the east terrace, [x, z]: the places the recipe tests
# build them (tests/world_room_tests.py), clear of each other.
BUILDS = [("mace", [13.0, -5.6]), ("table", [10.4, -3.4])]


def main() -> int:
    world_id = room_world.open_room(world_room.valley())   # the world's ground, bare
    try:
        for recipe, at in BUILDS:
            answer = room_world.call(world_id, "build_recipe", {"recipe": recipe, "at_m": at})
            if "error" in answer:
                print(f"REFUSED: {recipe} at {at}: {answer['error']}", file=sys.stderr)
                return 1
            print(f"  {recipe:6s} at {at}: {', '.join(answer['parts'])}")
        spec = room_world.export_spec(room_world.entry_of(world_id))
    finally:
        room_world.close_room(world_id)
    OUT.write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
