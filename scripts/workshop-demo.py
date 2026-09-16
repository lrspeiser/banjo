#!/usr/bin/env python3
"""Print a few cheap Workshop Mode candidates and one materialization plan.

Run from the repository root:

    python scripts/workshop-demo.py

This demo never opens Banjo's physics engine and never mutates a live world.
It reads the same model the page and the agent read, so what it prints is what
they see.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.workshop import (
    ComponentLibrary,
    WorkshopSession,
    assemble,
    assemblies,
    feedback,
    materialize,
    variants,
)


def main() -> None:
    session = WorkshopSession(
        session_id="demo-workshop",
        world_revision="demo-frozen-world-r1",
        target="new table",
    )
    print("workshop session:", json.dumps(session.described()))
    print()

    library = ComponentLibrary()
    print("component families:", ", ".join(library.families()))
    print("assemblies:        ", ", ".join(a["assembly"] for a in assemblies()))
    print()

    base = assemble("table", design_id="work-table", purpose="a sturdy shop table",
                    parameters={"width_m": 1.4, "depth_m": 0.8, "height_m": 0.9,
                                "leg_section_m": 0.07, "aprons": 1},
                    library=library)
    measured = base.measure()
    print("base candidate: %d parts, %.1f kg, base %.2f x %.2f m, tips at %.1f deg"
          % (len(base.parts), measured["mass_kg"], *measured["support_footprint_m"],
             measured["tip_angle_deg"]))
    print()

    print("candidates, and what each one measures:")
    made = variants(base, {"leg_style": ["straight", "splayed", "tapered"],
                           "leg_section_m": [0.05, 0.08]})
    plans = {}
    for candidate in made:
        m, plan = candidate.measure(), materialize(candidate)
        plans.setdefault(plan["fingerprint"], []).append(candidate.design_id)
        print("  %-16s %-8s %3.0f mm legs  %6.1f kg  base %.2f x %.2f m  tips at %4.1f deg"
              % (candidate.design_id, candidate.parameters["leg_style"],
                 candidate.parameters["leg_section_m"] * 1000, m["mass_kg"],
                 *m["support_footprint_m"], m["tip_angle_deg"]))
    together = [ids for ids in plans.values() if len(ids) > 1]
    if together:
        print("  at a 40 mm cell these arrive as one object:",
              "; ".join(", ".join(ids) for ids in together))
    print()

    steadiest = max(made, key=lambda d: d.measure()["tip_angle_deg"])
    print("hardest to tip:", steadiest.design_id)
    print("feedback:", json.dumps(feedback(steadiest, rating=5, selected=True,
                                           note="widest base of the six")))
    print()
    print("materialization plan for it:")
    print(json.dumps(materialize(steadiest), indent=2))


if __name__ == "__main__":
    main()
